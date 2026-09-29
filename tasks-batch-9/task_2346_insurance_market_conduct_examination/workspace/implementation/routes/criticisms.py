"""Criticism issuance, rebuttal rounds and finalization (PRD §3.6, §3.7)."""

from flask import Blueprint

import validation as v
from db import db, new_record, now_iso, touch
from errors import ApiError
from middleware import (
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_INSURER_RESPONDENT,
    ROLE_SUPERVISING_EXAMINER,
    authorize,
    current_user_id,
)
from response import paginated, success
from routes.common import filter_equals, str_query
from routes.examinations import EXAM_RECORD_READ_ROLES
from services import calculations as calc
from services import derive, serialize, transitions
from services.guards import (
    ensure_exam_subject,
    ensure_exam_writable,
    get_area,
    get_criticism,
    get_exam,
)

bp = Blueprint("criticisms", __name__)

SEVERITIES = ("MINOR", "MATERIAL", "EGREGIOUS")
POSITIONS = ("CONCUR", "PARTIAL_CONCUR", "DISPUTE")
DISPOSITIONS = ("SUSTAINED", "WITHDRAWN")


@bp.post("/criticisms")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def create_criticism():
    payload = v.body()
    # Band 5 first: the examination, then the scope area, then its cross-parent case.
    exam_id = v.get_str(payload, "exam_id", min_len=1)
    scope_area_id = v.get_str(payload, "scope_area_id", min_len=1)
    exam = get_exam(exam_id)
    area = get_area(scope_area_id)
    if area["exam_id"] != exam["id"]:
        raise ApiError(
            "ERR_EXAM_RECORD_NOT_FOUND",
            "That scope area belongs to a different examination.",
        )

    statute_citation = v.get_str(payload, "statute_citation", min_len=1)
    severity = v.get_enum(payload, "severity", SEVERITIES)
    affected_file_count = v.get_int(payload, "affected_file_count", minimum=1)

    ensure_exam_writable(exam)
    if exam["status"] not in ("FIELDWORK", "CRITICISM"):
        raise ApiError(
            "ERR_EXAM_NOT_IN_CRITICISM_PHASE",
            "A criticism may only be issued while the examination is in FIELDWORK or "
            "CRITICISM; this examination is %s." % exam["status"],
        )
    if area["status"] != "TESTED":
        raise ApiError(
            "ERR_SCOPE_AREA_NOT_TESTED",
            "The referenced scope area is %s rather than TESTED." % area["status"],
        )
    _require_documented_fieldwork(exam)

    metrics = derive.area_metrics(area)
    if severity == "EGREGIOUS" and not metrics["tolerance_breached"]:
        raise ApiError(
            "ERR_NO_TOLERANCE_BREACH",
            "An EGREGIOUS criticism requires a scope area whose tolerance is breached.",
        )
    if affected_file_count > metrics["error_count"]:
        raise ApiError(
            "ERR_AFFECTED_FILES_EXCEED_ERRORS",
            "affected_file_count may not exceed the scope area's error_count.",
        )

    method, exposure = calc.restitution_exposure(
        severity,
        metrics["tolerance_breached"],
        derive.area_underpaid_total(area["id"]),
        metrics["reviewed_sample_count"],
        area["population_size"],
    )
    criticism = new_record(
        {
            "exam_id": exam["id"],
            "scope_area_id": area["id"],
            "statute_citation": statute_citation,
            "severity": severity,
            "affected_file_count": affected_file_count,
            "status": "ISSUED",
            "response_round": 0,
            "rebuttal_count": 0,
            "restitution_method": method,
            "restitution_exposure_cents": exposure,
            "penalty_units": 0,
            "issued_by_user_id": current_user_id(),
            "finalized_by_user_id": None,
            "finalized_at": None,
            "disposition_note": None,
        }
    )
    db.criticisms[criticism["id"]] = criticism
    touch(exam)
    return success(serialize.criticism(criticism), 201)


def _require_documented_fieldwork(exam):
    activities = derive.fieldwork_activities_of_exam(exam["id"])
    types = {activity["activity_type"] for activity in activities}
    if "SYSTEM_WALKTHROUGH" not in types:
        raise ApiError(
            "ERR_FIELDWORK_NOT_DOCUMENTED",
            "The examination holds no SYSTEM_WALKTHROUGH workpaper.",
        )
    if exam["mode"] == "ON_SITE" and "INTERVIEW" not in types:
        raise ApiError(
            "ERR_FIELDWORK_NOT_DOCUMENTED",
            "An ON_SITE examination also requires an INTERVIEW workpaper.",
        )


@bp.get("/criticisms")
@authorize(*EXAM_RECORD_READ_ROLES)
def list_criticisms():
    rows = derive.by_creation_criticisms()
    rows = filter_equals(rows, "exam_id", str_query("exam_id"))
    rows = filter_equals(rows, "scope_area_id", str_query("scope_area_id"))
    rows = filter_equals(rows, "status", str_query("status"))
    return paginated(rows, serialize.criticism)


@bp.get("/criticisms/<criticism_id>")
@authorize(*EXAM_RECORD_READ_ROLES)
def read_criticism(criticism_id):
    criticism = get_criticism(criticism_id)
    ensure_exam_subject(derive.exam_of_criticism(criticism))
    return success(serialize.criticism(criticism))


@bp.post("/criticisms/<criticism_id>/responses")
@authorize(ROLE_INSURER_RESPONDENT)
def create_response(criticism_id):
    criticism = get_criticism(criticism_id)
    exam = ensure_exam_subject(derive.exam_of_criticism(criticism))
    payload = v.body()
    position = v.get_enum(payload, "position", POSITIONS)
    narrative = v.require_narrative(payload, "narrative")
    offer = v.get_int(
        payload, "remediation_offer_cents", required=False, default=0, minimum=0
    )

    ensure_exam_writable(exam)
    if criticism["status"] != "ISSUED":
        raise ApiError(
            "ERR_CRITICISM_STATE_INVALID",
            "A carrier may only answer a criticism in ISSUED; this criticism is %s."
            % criticism["status"],
        )
    if criticism["response_round"] >= calc.MAX_RESPONSE_ROUNDS:
        raise ApiError(
            "ERR_REBUTTAL_ROUNDS_EXHAUSTED",
            "The criticism has already consumed its three response rounds.",
        )

    round_number = criticism["response_round"] + 1
    record = new_record(
        {
            "criticism_id": criticism["id"],
            "round_number": round_number,
            "position": position,
            "narrative": narrative,
            "remediation_offer_cents": offer,
            "submitted_at": now_iso(),
        },
        versioned=False,
    )
    db.company_responses[record["id"]] = record
    criticism["response_round"] = round_number
    criticism["status"] = "RESPONDED"
    touch(criticism)
    return success(serialize.company_response(record), 201)


@bp.get("/criticisms/<criticism_id>/responses")
@authorize(*EXAM_RECORD_READ_ROLES)
def list_responses(criticism_id):
    criticism = get_criticism(criticism_id)
    ensure_exam_subject(derive.exam_of_criticism(criticism))
    rows = derive.responses_of_criticism(criticism["id"])
    rows = filter_equals(rows, "position", str_query("position"))
    return paginated(rows, serialize.company_response)


@bp.post("/criticisms/<criticism_id>/rebut")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def rebut_criticism(criticism_id):
    criticism = get_criticism(criticism_id)
    exam = derive.exam_of_criticism(criticism)
    payload = v.body()
    v.require_narrative(payload, "rebuttal_note")

    ensure_exam_writable(exam)
    if criticism["status"] != "RESPONDED":
        raise ApiError(
            "ERR_CRITICISM_STATE_INVALID",
            "Only a RESPONDED criticism can be rebutted; this criticism is %s."
            % criticism["status"],
        )
    if criticism["response_round"] >= calc.MAX_RESPONSE_ROUNDS:
        raise ApiError(
            "ERR_REBUTTAL_ROUNDS_EXHAUSTED",
            "The criticism has already consumed its three response rounds.",
        )

    criticism["status"] = "ISSUED"
    criticism["rebuttal_count"] += 1
    touch(criticism)
    return success(serialize.criticism(criticism))


@bp.post("/criticisms/<criticism_id>/finalize")
@authorize(ROLE_SUPERVISING_EXAMINER)
def finalize_criticism(criticism_id):
    criticism = get_criticism(criticism_id)
    if criticism["issued_by_user_id"] == current_user_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "A criticism may not be finalized by the examiner who issued it.",
        )
    exam = derive.exam_of_criticism(criticism)
    payload = v.body()
    disposition = v.get_enum(payload, "disposition", DISPOSITIONS)
    penalty_units = v.get_int(
        payload, "penalty_units", required=False, default=0, minimum=0
    )
    disposition_note = v.get_str(
        payload, "disposition_note", required=False, min_len=None
    )

    ensure_exam_writable(exam)
    if criticism["status"] != "RESPONDED":
        raise ApiError(
            "ERR_CRITICISM_STATE_INVALID",
            "Only a RESPONDED criticism can be finalized; this criticism is %s."
            % criticism["status"],
        )

    criticism["finalized_by_user_id"] = current_user_id()
    criticism["finalized_at"] = now_iso()
    criticism["disposition_note"] = disposition_note
    if disposition == "SUSTAINED":
        criticism["penalty_units"] = penalty_units
        criticism["status"] = "SUSTAINED"
    else:
        criticism["status"] = "WITHDRAWN"
    touch(criticism)
    if exam is not None:
        touch(exam)
        transitions.exam_maybe_enter_negotiation(exam)
    return success(serialize.criticism(criticism))
