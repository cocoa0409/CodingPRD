"""Milestone endpoints (PRD section 3.8)."""

from flask import Blueprint

from db import db, new_record, now_ts, serialize
from errors import ApiError
from middleware import (authenticate, get_bool, get_cents, get_enum, get_id_list,
                        get_int, get_str, json_body, pagination)
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import calculations as calc
from services import domain

bp = Blueprint("milestones", __name__)

READ_ROLES = ("ProgramAdmin", "AuditOfficer", "Subgrantee")
BASES = ("BUILD_PROGRESS", "INVOICED_COST")
MILESTONE_AWARD_STATES = ("CONSTRUCTION_AUTHORIZED", "IN_CONSTRUCTION")
OPEN_MILESTONE_STATES = ("PLANNED", "EVIDENCE_SUBMITTED", "HELD")


def _require_scope(award, location_ids):
    """Priority 60: every id must be AWARD_BOUND under this award."""
    for location_id in location_ids:
        location = db.locations.get(location_id)
        if (location is None
                or location.get("awarded_award_id") != award["id"]
                or location["eligibility_state"] != "AWARD_BOUND"):
            raise ApiError("ERR_LOCATION_NOT_IN_AWARD_SCOPE")


@bp.post("/broadband/awards/<award_id>/milestones")
def create_milestone(award_id):
    authenticate("ProgramAdmin")
    body = json_body()
    sequence_no = get_int(body, "sequence_no", minimum=1)
    description = get_str(body, "description")
    evidence_basis = get_enum(body, "evidence_basis", BASES)
    planned_ids = get_id_list(body, "planned_location_ids")
    is_final = get_bool(body, "is_final", required=False, default=False)

    award = domain.require_award(award_id)                               # priority 25
    if award["award_state"] not in MILESTONE_AWARD_STATES:               # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    _require_scope(award, planned_ids)                                   # priority 60

    siblings = domain.milestones_of_award(award["id"])
    if is_final:                                                         # priority 86
        for other in siblings:
            if other.get("is_final"):
                raise ApiError("ERR_FINAL_MILESTONE_CONFLICT")
    for other in siblings:
        if int(other["sequence_no"]) == sequence_no:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'sequence_no' must be unique within the award.")

    milestone = new_record({
        "award_id": award["id"],
        "sequence_no": sequence_no,
        "description": description,
        "evidence_basis": evidence_basis,
        "planned_location_ids": list(planned_ids),
        "is_final": is_final,
        "milestone_state": "PLANNED",
        "built_location_ids": [],
        "invoiced_cost_cents": None,
        "verified_location_count": 0,
        "payable_amount_cents": 0,
        "verified_by_user_id": None,
        "resubmission_count": 0,
        "rejection_reason": None,
    })
    db.milestones[milestone["id"]] = milestone
    return object_response(serialize(milestone), 201)


@bp.get("/broadband/awards/<award_id>/milestones")
def list_milestones(award_id):
    authenticate(*READ_ROLES)
    limit, offset = pagination()
    award = domain.require_award(award_id)
    return paginated(domain.milestones_of_award(award["id"]), limit, offset)


@bp.post("/broadband/awards/<award_id>/milestones/<milestone_id>/submit-evidence")
def submit_evidence(award_id, milestone_id):
    user_id, _role = authenticate("Subgrantee")
    body = json_body()
    built_ids = get_id_list(body, "built_location_ids")
    invoiced = get_cents(body, "invoiced_cost_cents", required=False)

    award = domain.require_award(award_id)                               # priority 25
    milestone = domain.require_milestone(award, milestone_id)             # priority 26
    application = domain.application_of_award(award)

    if application is None or user_id != application["subgrantee_id"]:    # priority 30
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if award["award_state"] not in MILESTONE_AWARD_STATES:               # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if award["compliance_state"] not in ("COMPLIANT", "CURED"):
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if milestone["milestone_state"] not in ("PLANNED", "REJECTED"):      # priority 46
        raise ApiError("ERR_MILESTONE_STATE_INVALID")
    planned = list(milestone["planned_location_ids"])
    for location_id in built_ids:                                        # priority 60
        if location_id not in planned:
            raise ApiError("ERR_LOCATION_NOT_IN_AWARD_SCOPE")
    _require_scope(award, built_ids)
    if milestone["evidence_basis"] == "INVOICED_COST" and invoiced is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'invoiced_cost_cents' is required when the evidence "
                       "basis is INVOICED_COST.")
    resubmitting = milestone["milestone_state"] == "REJECTED"
    if resubmitting and int(milestone["resubmission_count"]) >= calc.MAX_MILESTONE_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED")                 # priority 79

    assign(milestone, "milestone_state", "EVIDENCE_SUBMITTED")
    assign(milestone, "built_location_ids", list(built_ids))
    if invoiced is not None:
        assign(milestone, "invoiced_cost_cents", invoiced)
    if resubmitting:
        assign(milestone, "resubmission_count", int(milestone["resubmission_count"]) + 1)
    touch(milestone)
    return object_response(serialize(milestone))


@bp.post("/broadband/awards/<award_id>/milestones/<milestone_id>/verify")
def verify_milestone(award_id, milestone_id):
    user_id, _role = authenticate("AuditOfficer", "ProgramAdmin")
    body = json_body()
    outcome = get_enum(body, "outcome", ("APPROVED", "REJECTED"))
    rejection_reason = get_str(body, "rejection_reason", required=False)
    if outcome == "REJECTED" and rejection_reason is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'rejection_reason' is required on a rejection.")

    award = domain.require_award(award_id)                               # priority 25
    milestone = domain.require_milestone(award, milestone_id)             # priority 26
    program = domain.program_of_award(award)

    if award["award_state"] not in MILESTONE_AWARD_STATES:               # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if milestone["milestone_state"] != "EVIDENCE_SUBMITTED":             # priority 46
        raise ApiError("ERR_MILESTONE_STATE_INVALID")

    verified_ids = list(milestone["built_location_ids"] or [])
    if outcome == "APPROVED":
        _require_scope(award, verified_ids)                              # priority 60
        for location_id in verified_ids:
            location = db.locations[location_id]
            if location["service_state"] != "UNDER_CONSTRUCTION":
                raise ApiError("ERR_LOCATION_NOT_IN_AWARD_SCOPE",
                               "Every verified location must be under construction.")
        if milestone.get("is_final"):                                    # priority 86
            for other in domain.milestones_of_award(award["id"]):
                if (other["id"] != milestone["id"]
                        and other["milestone_state"] in OPEN_MILESTONE_STATES):
                    raise ApiError("ERR_FINAL_MILESTONE_CONFLICT")

        verified_count = len(verified_ids)
        payable = calc.milestone_payable(award, program, milestone, verified_count)
        assign(milestone, "milestone_state", "APPROVED")
        assign(milestone, "verified_location_count", verified_count)
        assign(milestone, "payable_amount_cents", int(payable))
        assign(milestone, "verified_by_user_id", user_id)
        touch(milestone)
        for location_id in verified_ids:
            location = db.locations[location_id]
            assign(location, "service_state", "SERVICE_AVAILABLE")
            touch(location)
    else:
        assign(milestone, "milestone_state", "REJECTED")
        assign(milestone, "rejection_reason", rejection_reason)
        assign(milestone, "payable_amount_cents", 0)
        assign(milestone, "verified_by_user_id", user_id)
        touch(milestone)

    assign(award, "last_verifier_user_id", user_id)
    domain.refresh_award(award)
    touch(award)
    return object_response(serialize(milestone))


@bp.post("/broadband/awards/<award_id>/milestones/<milestone_id>/disburse")
def disburse_milestone(award_id, milestone_id):
    authenticate("ProgramAdmin")
    award = domain.require_award(award_id)                               # priority 25
    milestone = domain.require_milestone(award, milestone_id)             # priority 26
    program = domain.program_of_award(award)

    if award["award_state"] not in MILESTONE_AWARD_STATES:               # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if milestone["milestone_state"] != "APPROVED":                       # priority 46
        raise ApiError("ERR_MILESTONE_STATE_INVALID")
    if award["compliance_state"] not in ("COMPLIANT", "CURED"):
        raise ApiError("ERR_AWARD_STATE_INVALID")
    payable = int(milestone["payable_amount_cents"] or 0)
    if payable <= 0:                                                     # priority 92
        raise ApiError("ERR_NO_DISBURSABLE_AMOUNT")

    assign(milestone, "milestone_state", "DISBURSED")
    touch(milestone)

    domain.append_ledger(award, "DISBURSEMENT", payable,
                         "milestone:%s" % milestone["sequence_no"],
                         "Disbursement of milestone %s" % milestone["sequence_no"])

    for location_id in list(milestone["built_location_ids"] or []):
        location = db.locations.get(location_id)
        if location is None:
            continue
        if location["service_state"] == "SERVICE_AVAILABLE":
            assign(location, "service_state", "CERTIFIED")
            assign(location, "certified_at", now_ts())
            touch(location)

    if award["award_state"] == "CONSTRUCTION_AUTHORIZED":
        assign(award, "award_state", "IN_CONSTRUCTION")
    if milestone.get("is_final"):
        assign(award, "award_state", "CLOSED")
    domain.refresh_award(award)
    touch(award)
    if program is not None:
        domain.refresh_program(program)
    return object_response(serialize(milestone))
