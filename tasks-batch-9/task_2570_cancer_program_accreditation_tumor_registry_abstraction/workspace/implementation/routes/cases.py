"""Tumor case worklist, assignment and lifetime follow-up."""

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import all_of, clock_date, fmt_date, mark, parse_date
from errors import ApiError
from middleware import ANY_ROLE, actor, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("cases", __name__)


@bp.get(PREFIX + "/cases")
@endpoint(ANY_ROLE)
def list_cases():
    program_id = validate.q_str("program_id")
    entry_id = validate.q_str("entry_id")
    assigned_abstractor_id = validate.q_str("assigned_abstractor_id")
    case_state = validate.q_enum("case_state", spec.CASE_STATES)
    submission_state = validate.q_enum("submission_state",
                                       spec.CASE_SUBMISSION_STATES)
    timeliness_status = validate.q_enum("timeliness_status",
                                        spec.TIMELINESS_STATUSES)
    follow_up_status = validate.q_enum("follow_up_status",
                                       spec.FOLLOW_UP_STATUSES)
    items = all_of("case")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if entry_id is not None:
        items = [c for c in items if c["entry_id"] == entry_id]
    if assigned_abstractor_id is not None:
        items = [c for c in items
                 if c["assigned_abstractor_id"] == assigned_abstractor_id]
    if case_state is not None:
        items = [c for c in items if c["case_state"] == case_state]
    if submission_state is not None:
        items = [c for c in items if c["submission_state"] == submission_state]
    if timeliness_status is not None:
        items = [c for c in items if c["timeliness_status"] == timeliness_status]
    if follow_up_status is not None:
        items = [c for c in items if c["follow_up_status"] == follow_up_status]
    return page(items)


@bp.get(PREFIX + "/cases/<case_id>")
@endpoint(ANY_ROLE)
def read_case(case_id):
    case = need("case", case_id, "ERR_CASE_NOT_FOUND")
    return ok(case)


@bp.post(PREFIX + "/cases/<case_id>/assign")
@endpoint(["RegistryManager"])
def assign_case(case_id):
    body = validate.body()
    abstractor_id = validate.f_str(body, "abstractor_id")

    case = need("case", case_id, "ERR_CASE_NOT_FOUND")
    abstractor = need("abstractor", abstractor_id, "ERR_ABSTRACTOR_NOT_FOUND")
    program = db.get("program", case["program_id"])

    if case["case_state"] != "IDENTIFIED":
        raise ApiError("ERR_CASE_NOT_ASSIGNABLE")
    if program["registry_posture"] == "FROZEN":
        raise ApiError("ERR_REGISTRY_FROZEN")
    if (program["registry_posture"] == "RESTRICTED"
            and abstractor["credential"] != "CTR"):
        raise ApiError("ERR_RESTRICTED_REQUIRES_CTR")
    if abstractor["employment_status"] != "ACTIVE":
        raise ApiError("ERR_ABSTRACTOR_NOT_ACTIVE")
    if parse_date(abstractor["certification_expires_on"]) < clock_date():
        raise ApiError("ERR_ABSTRACTOR_CERTIFICATION_EXPIRED")
    if abstractor["program_id"] != case["program_id"]:
        raise ApiError("ERR_ABSTRACTOR_PROGRAM_MISMATCH")
    cap = calcs.capacity_cap(abstractor["productivity_target_cases_per_day"])
    if abstractor["assigned_open_case_count"] >= cap:
        raise ApiError("ERR_ABSTRACTOR_CAPACITY_EXCEEDED")

    mark(case)
    case["assigned_abstractor_id"] = abstractor_id
    case["case_state"] = "ASSIGNED"
    services.refresh_case_timeliness(case)
    mark(abstractor)
    abstractor["assigned_open_case_count"] = (
        abstractor["assigned_open_case_count"] + 1)
    services.refresh_program_aggregates(program)
    return ok(case)


@bp.post(PREFIX + "/cases/<case_id>/unassign")
@endpoint(["RegistryManager"])
def unassign_case(case_id):
    body = validate.body()
    validate.f_str(body, "unassign_reason", required=False)

    case = need("case", case_id, "ERR_CASE_NOT_FOUND")
    if (case["case_state"] != "ASSIGNED"
            or case.get("assigned_abstractor_id") is None):
        raise ApiError("ERR_CASE_NOT_ASSIGNED")

    abstractor = db.get("abstractor", case["assigned_abstractor_id"])
    mark(case)
    case["assigned_abstractor_id"] = None
    case["case_state"] = "IDENTIFIED"
    services.refresh_case_timeliness(case)
    if abstractor is not None:
        mark(abstractor)
        abstractor["assigned_open_case_count"] = max(
            0, abstractor["assigned_open_case_count"] - 1)
    program = db.get("program", case["program_id"])
    if program is not None:
        services.refresh_program_aggregates(program)
    return ok(case)


@bp.post(PREFIX + "/cases/<case_id>/follow-up-contacts")
@endpoint(["RegistryManager", "RegistryAbstractor"])
def create_follow_up_contact(case_id):
    body = validate.body()
    contact_date = validate.f_date(body, "contact_date")
    contact_method = validate.f_enum(body, "contact_method",
                                     spec.CONTACT_METHODS)
    outcome = validate.f_enum(body, "outcome", spec.CONTACT_OUTCOMES)
    vital_status_at_contact = validate.f_enum(body, "vital_status_at_contact",
                                              spec.VITAL_STATUSES)

    case = need("case", case_id, "ERR_CASE_NOT_FOUND")

    if case["case_state"] != "COMPLETED":
        raise ApiError("ERR_CASE_NOT_COMPLETED")
    if contact_date > clock_date():
        raise ApiError("ERR_CONTACT_DATE_INVALID")
    if contact_date < parse_date(case["diagnosis_date"]):
        raise ApiError("ERR_CONTACT_DATE_INVALID")

    counts = outcome in spec.QUALIFYING_CONTACT_OUTCOMES
    contact = db.new_entity("contact", {
        "case_id": case_id,
        "contact_date": fmt_date(contact_date),
        "contact_method": contact_method,
        "outcome": outcome,
        "vital_status_at_contact": vital_status_at_contact,
        "recorded_by_user_id": actor(),
        "counts_for_follow_up": counts,
    }, versioned=False)

    mark(case)
    if counts:
        existing = parse_date(case.get("last_contact_date"))
        if existing is None or contact_date > existing:
            case["last_contact_date"] = fmt_date(contact_date)
    case["vital_status"] = vital_status_at_contact
    services.refresh_case_follow_up(case)

    program = db.get("program", case["program_id"])
    if program is not None:
        services.refresh_program_follow_up(program)
        services.refresh_program_aggregates(program)
    return ok(contact, 201)


@bp.get(PREFIX + "/follow-up-contacts")
@endpoint(ANY_ROLE)
def list_contacts():
    case_id = validate.q_str("case_id")
    outcome = validate.q_enum("outcome", spec.CONTACT_OUTCOMES)
    items = all_of("contact")
    if case_id is not None:
        items = [c for c in items if c["case_id"] == case_id]
    if outcome is not None:
        items = [c for c in items if c["outcome"] == outcome]
    return page(items)


@bp.get(PREFIX + "/follow-up-contacts/<contact_id>")
@endpoint(ANY_ROLE)
def read_contact(contact_id):
    contact = need("contact", contact_id, "ERR_CONTACT_NOT_FOUND")
    return ok(contact)
