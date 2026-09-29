"""InsurancePolicy endpoints: registration and settlement recording."""
from flask import Blueprint

from db import new_row, parse_instant, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.constants import POLICY_TYPES
from services.ledger import (
    applicant_of_facility,
    disaster_of_facility,
    insurance_dob_waterfall,
)
from validate import body, v_bool, v_enum, v_id, v_instant, v_int, v_str

bp = Blueprint("insurance", __name__)


@bp.route(PREFIX + "/insurance-policies", methods=["POST"])
def create_policy():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_facility = payload.get("facility_id")
    if isinstance(raw_facility, str):
        facility = find("facilities", raw_facility)
        if facility is not None:
            check_scope(actor, facility["applicant_id"])

    facility_id = v_id(payload, "facility_id")
    insurer_name = v_str(payload, "insurer_name")
    policy_type = v_enum(payload, "policy_type", POLICY_TYPES)
    coverage_limit_cents = v_int(payload, "coverage_limit_cents", minimum=0)
    effective_start_at = v_instant(payload, "effective_start_at")
    effective_end_at = v_instant(payload, "effective_end_at")
    deductible_cents = v_int(payload, "deductible_cents", required=False, default=0,
                             minimum=0)
    is_nfip = v_bool(payload, "is_nfip", required=False, default=False)

    require("facilities", facility_id)

    row = new_row("insurance_policies", {
        "facility_id": facility_id,
        "insurer_name": insurer_name,
        "policy_type": policy_type,
        "is_nfip": is_nfip,
        "coverage_limit_cents": coverage_limit_cents,
        "deductible_cents": deductible_cents,
        "effective_start_at": effective_start_at,
        "effective_end_at": effective_end_at,
        "settlement_amount_cents": 0,
        "settled_at": None,
        "allocated_cents": 0,
        "unallocated_cents": 0,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/insurance-policies", methods=["GET"])
def list_policies():
    authenticate(ALL_ROLES)
    return render_list("insurance_policies", {
        "facility_id": "facility_id",
        "policy_type": "policy_type",
    })


@bp.route(PREFIX + "/insurance-policies/<insurance_policy_id>", methods=["GET"])
def get_policy(insurance_policy_id):
    actor = authenticate(ALL_ROLES)
    policy = find("insurance_policies", insurance_policy_id)
    if policy is not None:
        facility = find("facilities", policy["facility_id"])
        if facility is not None:
            check_scope(actor, facility["applicant_id"])
    policy = require("insurance_policies", insurance_policy_id)
    return respond(policy)


@bp.route(PREFIX + "/insurance-policies/<insurance_policy_id>/record-settlement",
          methods=["POST"])
def record_settlement(insurance_policy_id):
    actor = authenticate(("GrantsOfficer",))
    policy = require("insurance_policies", insurance_policy_id)
    payload = body()

    settlement_amount_cents = v_int(payload, "settlement_amount_cents", minimum=0)
    settled_at = v_instant(payload, "settled_at")

    facility = find("facilities", policy["facility_id"])
    disaster = disaster_of_facility(facility) if facility else None
    if disaster is not None:
        incident_start = parse_instant(disaster["incident_start_at"])
        low = parse_instant(policy["effective_start_at"])
        high = parse_instant(policy["effective_end_at"])
        if low is None or high is None or not (low <= incident_start <= high):
            fail("ERR_POLICY_NOT_EFFECTIVE_AT_INCIDENT",
                 "the policy was not in force at the incident start")

    if settlement_amount_cents > policy["coverage_limit_cents"]:
        fail("ERR_SETTLEMENT_EXCEEDS_COVERAGE",
             "settlement_amount_cents exceeds the policy coverage limit")

    setf(policy, "settlement_amount_cents", settlement_amount_cents)
    setf(policy, "settled_at", settled_at)
    insurance_dob_waterfall(policy, settlement_amount_cents, actor.user_id)
    touch(policy)
    return respond(policy)
