"""Abstraction authoring, completeness scoring and the QA rework loop."""

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import (all_of, clock_date, clock_now, fmt_date, fmt_instant, mark,
                parse_date)
from errors import ApiError
from middleware import ANY_ROLE, actor, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("abstractions", __name__)

CLINICAL_FIELDS = ("stage_source", "t_category", "n_category", "m_category",
                   "stage_group", "first_treatment_date",
                   "treatment_modalities", "radiation_start_date",
                   "diagnostic_confirmation_code", "outcome_status",
                   "last_contact_date")


def _read_clinical(body, required_stage_source):
    values = {}
    values["stage_source"] = validate.f_enum(
        body, "stage_source", spec.STAGE_SOURCES,
        required=required_stage_source)
    values["t_category"] = validate.f_str(body, "t_category", required=False,
                                         allow_empty=True)
    values["n_category"] = validate.f_str(body, "n_category", required=False,
                                         allow_empty=True)
    values["m_category"] = validate.f_str(body, "m_category", required=False,
                                         allow_empty=True)
    values["stage_group"] = validate.f_enum(body, "stage_group",
                                            spec.STAGE_GROUPS, required=False)
    first_treatment = validate.f_date(body, "first_treatment_date",
                                      required=False)
    values["first_treatment_date"] = fmt_date(first_treatment)
    values["treatment_modalities"] = validate.f_enum_list(
        body, "treatment_modalities", spec.TREATMENT_MODALITIES,
        required=False)
    radiation = validate.f_date(body, "radiation_start_date", required=False)
    values["radiation_start_date"] = fmt_date(radiation)
    values["diagnostic_confirmation_code"] = validate.f_str(
        body, "diagnostic_confirmation_code", required=False, allow_empty=True)
    values["outcome_status"] = validate.f_enum(body, "outcome_status",
                                               spec.OUTCOME_STATUSES,
                                               required=False)
    last_contact = validate.f_date(body, "last_contact_date", required=False)
    values["last_contact_date"] = fmt_date(last_contact)
    return values


def _rescore(abstraction, case):
    mark(abstraction)
    missing, score = calcs.completeness(abstraction, case)
    abstraction["missing_required_fields"] = missing
    abstraction["completeness_score"] = score


@bp.post(PREFIX + "/abstractions")
@endpoint(["RegistryAbstractor"])
def create_abstraction():
    body = validate.body()
    case_id = validate.f_str(body, "case_id")
    abstractor_id = validate.f_str(body, "abstractor_id")
    expected_case_version = validate.f_int(body, "expected_case_version")
    supersedes_id = validate.f_str(body, "supersedes_abstraction_id",
                                   required=False)
    clinical = _read_clinical(body, required_stage_source=True)

    case = need("case", case_id, "ERR_CASE_NOT_FOUND")
    abstractor = need("abstractor", abstractor_id, "ERR_ABSTRACTOR_NOT_FOUND")

    if expected_case_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")

    if case["case_state"] not in ("ASSIGNED", "REWORK_PENDING"):
        raise ApiError("ERR_CASE_NOT_ABSTRACTABLE")

    program = db.get("program", case["program_id"])
    if program["registry_posture"] == "FROZEN":
        raise ApiError("ERR_REGISTRY_FROZEN")
    if abstractor["employment_status"] != "ACTIVE":
        raise ApiError("ERR_ABSTRACTOR_NOT_ACTIVE")
    if parse_date(abstractor["certification_expires_on"]) < clock_date():
        raise ApiError("ERR_ABSTRACTOR_CERTIFICATION_EXPIRED")
    if abstractor["program_id"] != case["program_id"]:
        raise ApiError("ERR_ABSTRACTOR_PROGRAM_MISMATCH")
    assigned = case.get("assigned_abstractor_id")
    if assigned is None or actor() != assigned or abstractor_id != assigned:
        raise ApiError("ERR_NOT_ASSIGNED_ABSTRACTOR")

    live = [a for a in services.abstractions_of_case(case_id)
            if a["abstraction_state"] not in ("REJECTED", "SUPERSEDED")]
    if live and supersedes_id is None:
        raise ApiError("ERR_SUPERSEDE_TARGET_REQUIRED")

    target = None
    if supersedes_id is not None:
        target = db.get("abstraction", supersedes_id)
        if (target is None or target["case_id"] != case_id
                or target["abstraction_state"] not in ("DRAFT",
                                                       "REWORK_REQUIRED")):
            raise ApiError("ERR_SUPERSEDE_TARGET_INVALID")

    fields = {
        "case_id": case_id,
        "abstractor_id": actor(),
        "supersedes_abstraction_id": supersedes_id,
        "missing_required_fields": [],
        "completeness_score": 0,
        "abstraction_state": "DRAFT",
        "rework_round": target["rework_round"] if target is not None else 0,
        "submitted_at": None,
        "approved_at": None,
        "qa_reviewer_user_id": None,
    }
    fields.update(clinical)
    if fields.get("treatment_modalities") is None:
        fields["treatment_modalities"] = []
    abstraction = db.new_entity("abstraction", fields)
    _rescore(abstraction, case)

    if target is not None:
        mark(target)
        target["abstraction_state"] = "SUPERSEDED"

    mark(case)
    case["case_state"] = "IN_ABSTRACTION"
    services.refresh_case_timeliness(case)
    services.refresh_program_aggregates(program)
    return ok(abstraction, 201)


@bp.get(PREFIX + "/abstractions")
@endpoint(ANY_ROLE)
def list_abstractions():
    case_id = validate.q_str("case_id")
    abstractor_id = validate.q_str("abstractor_id")
    supersedes_abstraction_id = validate.q_str("supersedes_abstraction_id")
    abstraction_state = validate.q_enum("abstraction_state",
                                        spec.ABSTRACTION_STATES)
    items = all_of("abstraction")
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    if abstractor_id is not None:
        items = [a for a in items if a["abstractor_id"] == abstractor_id]
    if supersedes_abstraction_id is not None:
        items = [a for a in items
                 if a["supersedes_abstraction_id"] == supersedes_abstraction_id]
    if abstraction_state is not None:
        items = [a for a in items
                 if a["abstraction_state"] == abstraction_state]
    return page(items)


@bp.get(PREFIX + "/abstractions/<abstraction_id>")
@endpoint(ANY_ROLE)
def read_abstraction(abstraction_id):
    abstraction = need("abstraction", abstraction_id,
                       "ERR_ABSTRACTION_NOT_FOUND")
    return ok(abstraction)


@bp.post(PREFIX + "/abstractions/<abstraction_id>/submit-qa")
@endpoint(["RegistryAbstractor"])
def submit_qa(abstraction_id):
    body = validate.body()
    validate.f_str(body, "submit_note", required=False)

    abstraction = need("abstraction", abstraction_id,
                       "ERR_ABSTRACTION_NOT_FOUND")
    if abstraction["abstraction_state"] != "DRAFT":
        raise ApiError("ERR_ABSTRACTION_NOT_DRAFT")
    if actor() != abstraction["abstractor_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ABSTRACTOR")
    if (abstraction["completeness_score"] < spec.COMPLETENESS_SUBMIT_MIN
            or abstraction["missing_required_fields"]):
        raise ApiError("ERR_ABSTRACTION_INCOMPLETE")

    mark(abstraction)
    abstraction["abstraction_state"] = "SUBMITTED_FOR_QA"
    abstraction["submitted_at"] = fmt_instant(clock_now())

    case = db.get("case", abstraction["case_id"])
    if case is not None:
        mark(case)
        case["case_state"] = "QA_PENDING"
        services.refresh_case_timeliness(case)
        program = db.get("program", case["program_id"])
        if program is not None:
            services.refresh_program_aggregates(program)
    return ok(abstraction)


@bp.post(PREFIX + "/abstractions/<abstraction_id>/qa-decision")
@endpoint(["QaReviewer"])
def qa_decision(abstraction_id):
    body = validate.body()
    verdict = validate.f_enum(body, "verdict", spec.QA_VERDICTS)
    validate.f_str(body, "reviewer_note", required=False)

    abstraction = need("abstraction", abstraction_id,
                       "ERR_ABSTRACTION_NOT_FOUND")
    if abstraction["abstraction_state"] != "SUBMITTED_FOR_QA":
        raise ApiError("ERR_ABSTRACTION_NOT_IN_QA")

    case = db.get("case", abstraction["case_id"])
    reviewer = db.get("abstractor", actor())
    if reviewer is not None and reviewer["employment_status"] != "ACTIVE":
        raise ApiError("ERR_ABSTRACTOR_NOT_ACTIVE")
    if actor() == abstraction["abstractor_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")
    if (reviewer is not None and case is not None
            and reviewer["program_id"] != case["program_id"]):
        raise ApiError("ERR_ABSTRACTOR_PROGRAM_MISMATCH")

    program = db.get("program", case["program_id"]) if case else None
    author = db.get("abstractor", abstraction["abstractor_id"])

    mark(abstraction)
    abstraction["qa_reviewer_user_id"] = actor()

    if verdict == "APPROVED":
        abstraction["abstraction_state"] = "APPROVED"
        abstraction["approved_at"] = fmt_instant(clock_now())
        if case is not None:
            mark(case)
            case["case_state"] = "COMPLETED"
            case["completed_on"] = fmt_date(clock_date())
            services.refresh_case_timeliness(case)
            services.refresh_case_follow_up(case)
        if author is not None:
            mark(author)
            author["assigned_open_case_count"] = max(
                0, author["assigned_open_case_count"] - 1)
            services.refresh_abstractor_productivity(author)
        if program is not None:
            services.refresh_program_follow_up(program)
            services.refresh_program_aggregates(program)
    elif verdict == "REWORK_REQUIRED":
        abstraction["abstraction_state"] = "REWORK_REQUIRED"
        if case is not None:
            mark(case)
            case["case_state"] = "IN_ABSTRACTION"
            services.refresh_case_timeliness(case)
        if program is not None:
            services.refresh_program_aggregates(program)
    else:
        abstraction["abstraction_state"] = "REJECTED"
        if case is not None:
            mark(case)
            case["case_state"] = "IDENTIFIED"
            case["assigned_abstractor_id"] = None
            services.refresh_case_timeliness(case)
        if author is not None:
            mark(author)
            author["assigned_open_case_count"] = max(
                0, author["assigned_open_case_count"] - 1)
        if program is not None:
            services.refresh_program_aggregates(program)
    return ok(abstraction)


@bp.post(PREFIX + "/abstractions/<abstraction_id>/reopen-draft")
@endpoint(["RegistryAbstractor"])
def reopen_draft(abstraction_id):
    body = validate.body()
    clinical = _read_clinical(body, required_stage_source=False)

    abstraction = need("abstraction", abstraction_id,
                       "ERR_ABSTRACTION_NOT_FOUND")
    if abstraction["abstraction_state"] != "REWORK_REQUIRED":
        raise ApiError("ERR_ABSTRACTION_NOT_REWORKABLE")
    if actor() != abstraction["abstractor_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ABSTRACTOR")
    case = db.get("case", abstraction["case_id"])
    if case is None or case["case_state"] not in ("IN_ABSTRACTION",
                                                  "REWORK_PENDING"):
        raise ApiError("ERR_CASE_NOT_ABSTRACTABLE")
    if abstraction["rework_round"] >= spec.REWORK_ROUND_MAX:
        raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")

    mark(abstraction)
    for field in CLINICAL_FIELDS:
        if field in body:
            abstraction[field] = clinical[field]
    if abstraction.get("treatment_modalities") is None:
        abstraction["treatment_modalities"] = []
    abstraction["rework_round"] = abstraction["rework_round"] + 1
    abstraction["abstraction_state"] = "DRAFT"
    _rescore(abstraction, case)

    db.force_touch(case)
    case["case_state"] = "IN_ABSTRACTION"
    services.refresh_case_timeliness(case)
    program = db.get("program", case["program_id"])
    if program is not None:
        services.refresh_program_aggregates(program)
    return ok(abstraction)
