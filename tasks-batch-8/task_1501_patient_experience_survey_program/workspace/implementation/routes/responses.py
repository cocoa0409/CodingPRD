"""SurveyResponse endpoints (PRD 3.4, 3.5): intake (single + bulk),
adjudication, and voiding."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CYCLE_NOT_FIELDING,
    ERR_CASE_NOT_IN_FIELD,
    ERR_VENDOR_CASE_MISMATCH,
    ERR_RESPONSE_ALREADY_EXISTS,
    ERR_CYCLE_NOT_RECONCILING,
    ERR_RESPONSE_NOT_PENDING_REVIEW,
    ERR_CYCLE_LOCKED,
    ERR_RESPONSE_NOT_VOIDABLE,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import response_view
from services.core import live_response_for_case, recompute_cycle_derived, RESPONSE_LIVE
from util import (
    get_json_body, reject_unknown_fields, require_string, require_enum,
    require_score, require_id_list, get_or_404, parse_pagination, paginate,
    sort_created, query_arg, parse_iso8601, parse_iso_date,
)

bp = Blueprint("responses", __name__)

MODES = {"MAIL", "PHONE"}
DECISIONS = {"INCLUDE", "EXCLUDE"}

INTAKE_FIELDS = {
    "case_id", "mode_used", "nurse_comm_score", "doctor_comm_score",
    "cleanliness_score", "overall_rating_score", "comment_text",
}
IMPORT_FIELDS = {
    "case_ids", "mode_used", "nurse_comm_score", "doctor_comm_score",
    "cleanliness_score", "overall_rating_score", "comment_text",
}


def _validate_score_block(body: dict) -> dict:
    return {
        "mode_used": require_enum(body, "mode_used", MODES),
        "nurse_comm_score": require_score(body, "nurse_comm_score"),
        "doctor_comm_score": require_score(body, "doctor_comm_score"),
        "cleanliness_score": require_score(body, "cleanliness_score"),
        "overall_rating_score": require_score(body, "overall_rating_score"),
        "comment_text": _optional_comment(body),
    }


def _optional_comment(body: dict):
    value = body.get("comment_text")
    if value is not None and not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Field comment_text must be a string")
    return value


def _check_intake_target(case: dict, user_id: str, batch_seen: set) -> dict:
    """Per-item intake guards. Returns the parent cycle.

    Order: ownership (2.5) -> cycle posture (4) -> one live response (the
    specific already-exists condition) -> case IN_FIELD (4, entity-local).
    """
    if user_id != case["vendor_id"]:
        raise_err(ERR_VENDOR_CASE_MISMATCH,
                  "VendorOperator may only submit responses for cases owned by their vendor")
    cycle = db.cycles.get(case["cycle_id"])
    if cycle is None or cycle["status"] != "FIELDING":
        raise_err(ERR_CYCLE_NOT_FIELDING,
                  "Response intake requires the parent cycle to be FIELDING")
    if case["id"] in batch_seen or live_response_for_case(case["id"]) is not None:
        raise_err(ERR_RESPONSE_ALREADY_EXISTS,
                  "The case already has a live response")
    if case["status"] != "IN_FIELD":
        raise_err(ERR_CASE_NOT_IN_FIELD,
                  "Response intake requires the case to be IN_FIELD")
    return cycle


def _record_response(case: dict, cycle: dict, scores: dict) -> dict:
    received_at = db.clock_now()
    is_late = (
        parse_iso8601(received_at, "received_at").date()
        > parse_iso_date(cycle["fielding_end_date"])
    )
    response = db.stamp_new({
        "case_id": case["id"],
        "cycle_id": case["cycle_id"],
        "mode_used": scores["mode_used"],
        "nurse_comm_score": scores["nurse_comm_score"],
        "doctor_comm_score": scores["doctor_comm_score"],
        "cleanliness_score": scores["cleanliness_score"],
        "overall_rating_score": scores["overall_rating_score"],
        "comment_text": scores["comment_text"],
        "received_at": received_at,
        "is_late": is_late,
        "status": "PENDING_REVIEW" if is_late else "ACCEPTED",
        "has_escalated_recovery": False,
    })
    db.responses[response["id"]] = response
    case["status"] = "RESPONDED"
    db.touch(case)
    recompute_cycle_derived(cycle)
    db.touch(cycle)
    return response


@bp.route("/api/responses", methods=["POST"])
@require_roles("VendorOperator")
def create_response(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, INTAKE_FIELDS)
    case_id = require_string(body, "case_id")
    case = get_or_404(db.sample_cases, case_id, "SampleCase")
    cycle = _check_intake_target(case, _user_id, set())
    scores = _validate_score_block(body)
    response = _record_response(case, cycle, scores)
    return success_object(response_view(response), 201)


@bp.route("/api/responses/import", methods=["POST"])
@require_roles("VendorOperator")
def import_responses(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, IMPORT_FIELDS)
    case_ids = require_id_list(body, "case_ids", minimum=1, maximum=500)
    scores = _validate_score_block(body)

    # Atomic: validate every item in listed order before recording any.
    batch_seen: set = set()
    targets = []
    for case_id in case_ids:
        case = get_or_404(db.sample_cases, case_id, "SampleCase")
        cycle = _check_intake_target(case, _user_id, batch_seen)
        batch_seen.add(case_id)
        targets.append((case, cycle))

    response_ids = []
    for case, cycle in targets:
        response = _record_response(case, cycle, scores)
        response_ids.append(response["id"])

    return success_object({
        "created_count": len(response_ids),
        "response_ids": response_ids,
    }, 201)


@bp.route("/api/responses", methods=["GET"])
@require_roles("Any")
def list_responses(_user_id: str, _role: str):
    items = list(db.responses.values())
    for param in ("case_id", "cycle_id", "status", "mode_used"):
        value = query_arg(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([response_view(r) for r in page], limit, offset, total)


@bp.route("/api/responses/<responseId>", methods=["GET"])
@require_roles("Any")
def get_response(responseId: str, _user_id: str, _role: str):
    response = get_or_404(db.responses, responseId, "SurveyResponse")
    return success_object(response_view(response))


@bp.route("/api/responses/<responseId>/adjudicate", methods=["POST"])
@require_roles("DataSteward")
def adjudicate_response(responseId: str, _user_id: str, _role: str):
    response = get_or_404(db.responses, responseId, "SurveyResponse")
    body = get_json_body()
    reject_unknown_fields(body, {"decision"})
    decision = require_enum(body, "decision", DECISIONS)

    cycle = db.cycles.get(response["cycle_id"])
    # Cycle-posture errors precede entity-local state errors (PRD 2.6 tier 7).
    if cycle is None or cycle["status"] != "RECONCILIATION":
        raise_err(ERR_CYCLE_NOT_RECONCILING,
                  "Adjudication requires the cycle to be RECONCILIATION")
    if response["status"] != "PENDING_REVIEW":
        raise_err(ERR_RESPONSE_NOT_PENDING_REVIEW,
                  "Only a PENDING_REVIEW response can be adjudicated")

    response["status"] = "INCLUDED" if decision == "INCLUDE" else "EXCLUDED"
    db.touch(response)
    recompute_cycle_derived(cycle)
    db.touch(cycle)
    return success_object(response_view(response))


@bp.route("/api/responses/<responseId>/void", methods=["POST"])
@require_roles("DataSteward")
def void_response(responseId: str, _user_id: str, _role: str):
    response = get_or_404(db.responses, responseId, "SurveyResponse")
    body = get_json_body()
    reject_unknown_fields(body, {"reason"})
    require_string(body, "reason")

    cycle = db.cycles.get(response["cycle_id"])
    # Cycle-posture errors precede entity-local state errors (PRD 2.6 tier 7).
    if cycle is None or cycle["status"] not in ("FIELDING", "RECONCILIATION"):
        raise_err(ERR_CYCLE_LOCKED,
                  "Responses may be voided only while the cycle is FIELDING or RECONCILIATION")
    if response["status"] != "ACCEPTED":
        raise_err(ERR_RESPONSE_NOT_VOIDABLE,
                  "Only an ACCEPTED response can be voided")

    response["status"] = "VOIDED"
    db.touch(response)
    recompute_cycle_derived(cycle)
    db.touch(cycle)
    return success_object(response_view(response))
