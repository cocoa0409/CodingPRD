"""Household and income-verification endpoints (PRD section 3.2)."""
from flask import Blueprint, request

import calc
import clock
import domain
import envelope
import errors
import fields
import guards
import store
from errors import ApiError
from guards import (APPLICANT, CONTRACTOR, PROGRAM_ADMIN, PROGRAM_REVIEWER,
                    authorize)

bp = Blueprint("households", __name__)


@bp.post("/households")
@authorize(APPLICANT, PROGRAM_ADMIN)
def create_household():
    payload = guards.body()
    record = {
        "program_id": fields.req_str(payload, "program_id", allow_empty=False),
        "applicant_name": fields.req_str(payload, "applicant_name", allow_empty=False),
        "email": fields.req_str(payload, "email", allow_empty=False),
        "service_address_line1": fields.req_str(payload, "service_address_line1", allow_empty=False),
        "county_code": fields.req_str(payload, "county_code", allow_empty=False),
        "utility_territory_code": fields.req_str(payload, "utility_territory_code", allow_empty=False),
        "household_size": fields.req_int(payload, "household_size", minimum=1),
        "existing_panel_amps": fields.req_int(payload, "existing_panel_amps", minimum=0),
        "ami_percent": None,
        "income_tier": None,
        "rebate_cap_cents": 0,
        "lifetime_cap_remaining_cents": 0,
        "encumbered_cents": 0,
    }
    domain.get_program(record["program_id"])
    household = store.new_record(record)
    store.households[household["id"]] = household
    return envelope.object_response(store.public(household), 201)


@bp.get("/households/<household_id>")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_household(household_id):
    household = domain.get_household(household_id)
    if guards.actor_role() == APPLICANT and guards.actor_id() != household["id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER)
    return envelope.object_response(store.public(household))


@bp.post("/households/<household_id>/income-verifications")
@authorize(APPLICANT, PROGRAM_ADMIN)
def create_income_verification(household_id):
    payload = guards.body()
    record = {
        "annual_household_income_cents": fields.req_int(
            payload, "annual_household_income_cents", minimum=0),
        "county_median_income_cents": fields.req_int(
            payload, "county_median_income_cents", minimum=1),
        "household_size_attested": fields.req_int(payload, "household_size_attested", minimum=1),
        "document_reference": fields.opt_str(payload, "document_reference"),
    }
    household = domain.get_household(household_id)
    if guards.actor_role() == APPLICANT and guards.actor_id() != household["id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER)
    if domain.verified_income_verification(household["id"]) is not None:
        raise ApiError(errors.ERR_INCOME_TIER_ALREADY_VERIFIED)

    record.update({
        "household_id": household["id"],
        "status": "SUBMITTED",
        "computed_ami_percent": None,
        "assigned_income_tier": None,
        "assigned_cap_cents": 0,
        "submitted_by_user_id": guards.actor_id(),
        "verified_by_user_id": None,
        "verified_at": None,
        "reviewer_notes": None,
    })
    verification = store.new_record(record)
    store.income_verifications[verification["id"]] = verification
    return envelope.object_response(store.public(verification), 201)


@bp.get("/households/<household_id>/income-verifications")
@authorize(APPLICANT, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_income_verifications(household_id):
    limit, offset = guards.pagination()
    status = request.args.get("status")
    household = domain.get_household(household_id)
    records = store.ordered(
        store.income_verifications,
        lambda v: v["household_id"] == household["id"] and (status is None or v["status"] == status),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/income-verifications/<verification_id>/verify")
@authorize(PROGRAM_REVIEWER)
def verify_income_verification(verification_id):
    payload = guards.body()
    decision = fields.req_enum(payload, "decision", ("VERIFY", "REJECT"))
    notes = fields.opt_str(payload, "reviewer_notes")
    verification = domain.get_income_verification(verification_id)
    household = domain.get_household(verification["household_id"])
    verified_elsewhere = domain.verified_income_verification(household["id"])

    if verification["status"] != "SUBMITTED":
        if verified_elsewhere is not None:
            raise ApiError(errors.ERR_INCOME_TIER_ALREADY_VERIFIED)
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    if decision == "VERIFY" and verified_elsewhere is not None:
        raise ApiError(errors.ERR_INCOME_TIER_ALREADY_VERIFIED)
    if guards.actor_id() == verification["submitted_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES)

    verification["verified_by_user_id"] = guards.actor_id()
    verification["verified_at"] = clock.now_iso()
    if notes is not None:
        verification["reviewer_notes"] = notes

    if decision == "REJECT":
        verification["status"] = "REJECTED"
        store.touch(verification)
        return envelope.object_response(store.public(verification))

    program = domain.get_program(household["program_id"])
    outcome = calc.income_tier_assignment(program, verification)
    verification["status"] = "VERIFIED"
    verification["computed_ami_percent"] = outcome["ami_percent"]
    verification["assigned_income_tier"] = outcome["income_tier"]
    verification["assigned_cap_cents"] = outcome["cap_cents"]
    store.touch(verification)

    household["ami_percent"] = outcome["ami_percent"]
    household["income_tier"] = outcome["income_tier"]
    household["rebate_cap_cents"] = outcome["cap_cents"]
    household["lifetime_cap_remaining_cents"] = outcome["cap_cents"] - household["encumbered_cents"]
    store.touch(household)

    return envelope.object_response(store.public(verification))
