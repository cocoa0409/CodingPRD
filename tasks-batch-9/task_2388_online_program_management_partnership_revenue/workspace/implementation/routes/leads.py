"""Lead funnel and lead-to-enrollment conversion."""

from flask import Blueprint, request

import constants as C
import db
import serializers
from db import store, touch
from errors import ApiError, bad_request
from middleware import PARTNER, authenticate, body, check_scope
from response import object_response
from routes.common import (get_counselor, get_lead, get_partnership, get_program,
                           listing)
from services.derive import (recompute_counselor_pipeline, recompute_partnership,
                             recompute_program)
from services.money import D, parse_iso_date, rhu_int
from validation import Field, enum_filter, pagination_args, validate_body

bp = Blueprint("leads", __name__)

READ_ROLES = ("PlatformAdmin", "UniversityProvost", "UniversityBursar",
              "ComplianceAuditor", "PartnerAccountLead")

CREATE_SPEC = {
    "program_id": Field("string", required=True),
    "counselor_id": Field("string", required=True),
    "source_channel": Field("enum", required=True, enum=C.LEAD_SOURCE_CHANNELS),
    "prospect_external_id": Field("string", required=True),
}

ADVANCE_SPEC = {
    "action": Field("enum", required=True, enum=("CONTACT", "APPLY", "DISQUALIFY")),
    "hours_to_first_contact": Field("integer", minimum=0),
    "disqualification_reason": Field("enum", enum=C.DISQUALIFICATION_REASONS),
}

ENROLL_SPEC = {
    "student_external_id": Field("string", required=True),
    "credits_enrolled": Field("integer", required=True, minimum=0),
    "term_start_date": Field("date", required=True),
    "term_end_date": Field("date", required=True),
}

ADVANCE_TRANSITIONS = {
    "CONTACT": (("NEW",), "CONTACTED"),
    "APPLY": (("CONTACTED",), "APPLIED"),
    "DISQUALIFY": (("NEW", "CONTACTED", "APPLIED"), "DISQUALIFIED"),
}


def _partnership_id_of(lead):
    program = store.programs.get(lead["program_id"])
    return program["partnership_id"] if program else None


@bp.post("/leads")
def create():
    uid, role = authenticate(("PartnerAccountLead",))
    values = validate_body(body(), CREATE_SPEC)
    program = get_program(values["program_id"])
    counselor = get_counselor(values["counselor_id"])
    check_scope(role, uid, program["partnership_id"])

    if program["status"] != "LAUNCHED":
        raise ApiError("ERR_PROGRAM_INVALID_STATE")
    if counselor["incentive_eligibility"] == "PROHIBITED_PLAN_ON_FILE":
        raise ApiError("ERR_COUNSELOR_INCENTIVE_SUSPENDED")

    partnership = get_partnership(program["partnership_id"])
    if db.current_date() > parse_iso_date(partnership["expiry_date"]):
        raise ApiError("ERR_CONTRACT_TERM_EXPIRED")

    lead = db.base_entity()
    lead.update({
        "program_id": program["id"],
        "counselor_id": counselor["id"],
        "source_channel": values["source_channel"],
        "prospect_external_id": values["prospect_external_id"],
        "status": "NEW",
        "hours_to_first_contact": None,
        "qualified_at": None,
        "disqualification_reason": None,
    })
    store.leads[lead["id"]] = lead
    recompute_counselor_pipeline(counselor)
    return object_response(serializers.lead(lead), 201)


@bp.get("/leads/<lead_id>")
def read(lead_id):
    uid, role = authenticate(READ_ROLES)
    lead = get_lead(lead_id)
    check_scope(role, uid, _partnership_id_of(lead))
    return object_response(serializers.lead(lead))


@bp.get("/leads")
def index():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_args(request.args)
    status = enum_filter(request.args, "status", C.LEAD_STATUSES)
    program_id = request.args.get("program_id")
    counselor_id = request.args.get("counselor_id")

    if role == PARTNER and program_id is not None:
        program = store.programs.get(program_id)
        if program is not None and program["partnership_id"] != uid:
            raise ApiError("ERR_PARTNERSHIP_SCOPE_VIOLATION")

    items = db.sort_created(list(store.leads.values()))
    if program_id is not None:
        items = [l for l in items if l["program_id"] == program_id]
    if counselor_id is not None:
        items = [l for l in items if l["counselor_id"] == counselor_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if role == PARTNER:
        items = [l for l in items if _partnership_id_of(l) == uid]
    return listing(items, serializers.lead, limit, offset)


@bp.post("/leads/<lead_id>/advance")
def advance(lead_id):
    uid, role = authenticate(("PartnerAccountLead",))
    values = validate_body(body(), ADVANCE_SPEC)
    action = values["action"]

    if action == "CONTACT" and "hours_to_first_contact" not in values:
        raise bad_request("hours_to_first_contact is required on CONTACT.")
    if action == "DISQUALIFY" and "disqualification_reason" not in values:
        raise bad_request("disqualification_reason is required on DISQUALIFY.")

    lead = get_lead(lead_id)
    check_scope(role, uid, _partnership_id_of(lead))
    program = get_program(lead["program_id"])

    if action == "APPLY" and program["status"] != "LAUNCHED":
        raise ApiError("ERR_PROGRAM_INVALID_STATE")

    sources, target = ADVANCE_TRANSITIONS[action]
    if lead["status"] not in sources:
        raise ApiError("ERR_LEAD_INVALID_STATE")

    if action == "CONTACT":
        lead["hours_to_first_contact"] = values["hours_to_first_contact"]
    elif action == "APPLY":
        lead["qualified_at"] = db.now_iso()
    elif action == "DISQUALIFY":
        lead["disqualification_reason"] = values["disqualification_reason"]

    lead["status"] = target
    touch(lead)

    counselor = store.counselors.get(lead["counselor_id"])
    if counselor is not None:
        recompute_counselor_pipeline(counselor)
    return object_response(serializers.lead(lead))


@bp.post("/leads/<lead_id>/enroll")
def enroll(lead_id):
    uid, role = authenticate(("UniversityBursar",))
    values = validate_body(body(), ENROLL_SPEC)
    lead = get_lead(lead_id)
    program = get_program(lead["program_id"])

    if program["status"] != "LAUNCHED":
        raise ApiError("ERR_PROGRAM_INVALID_STATE")
    if lead["status"] != "APPLIED":
        raise ApiError("ERR_LEAD_INVALID_STATE")

    counselor = store.counselors.get(lead["counselor_id"])
    if (counselor is not None
            and counselor["incentive_eligibility"] == "PROHIBITED_PLAN_ON_FILE"):
        raise ApiError("ERR_COUNSELOR_INCENTIVE_SUSPENDED")

    partnership = get_partnership(program["partnership_id"])
    if db.current_date() > parse_iso_date(partnership["expiry_date"]):
        raise ApiError("ERR_CONTRACT_TERM_EXPIRED")

    recompute_program(program)
    if program["total_enrollment_count"] >= program["enrollment_cap"]:
        raise ApiError("ERR_ENROLLMENT_CAP_REACHED")

    snapshot = program["tuition_per_credit_cents"]
    enrollment = db.base_entity()
    enrollment.update({
        "program_id": program["id"],
        "lead_id": lead["id"],
        "student_external_id": values["student_external_id"],
        "credits_enrolled": values["credits_enrolled"],
        "credits_completed": 0,
        "tuition_per_credit_snapshot_cents": snapshot,
        "tuition_charged_cents": rhu_int(D(values["credits_enrolled"]) * D(snapshot)),
        "term_start_date": values["term_start_date"],
        "term_end_date": values["term_end_date"],
        "status": "ENROLLED",
        "collected_cents": 0,
        "refunded_cents": 0,
        "recognized_to_date_cents": 0,
        "withdrawal_date": None,
        "refund_pct_applied": None,
        "days_elapsed_at_withdrawal": None,
    })
    store.enrollments[enrollment["id"]] = enrollment

    lead["status"] = "ENROLLED"
    touch(lead)

    recompute_program(program)
    if counselor is not None:
        recompute_counselor_pipeline(counselor)
    recompute_partnership(partnership)
    return object_response(serializers.enrollment(enrollment), 201)
