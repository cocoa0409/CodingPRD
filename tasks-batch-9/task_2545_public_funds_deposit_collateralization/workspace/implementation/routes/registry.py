"""The state's register: custodians, pooled collateral programs, public units."""

from flask import Blueprint

import db
import middleware as mw
from constants import (
    COLLATERAL_PROGRAM_PREFERENCES,
    CUSTODIAN_TYPES,
    DEFAULT_CONCENTRATION_LIMIT_BPS,
    DEFAULT_MINIMUM_POOL_PCT_BPS,
    DEFAULT_TRI_PARTY_CAPABLE,
    DEPOSITORY_APPROVAL_STATUSES,
    MAX_CONCENTRATION_LIMIT_BPS,
    MAX_MINIMUM_POOL_PCT_BPS,
    MIN_CONCENTRATION_LIMIT_BPS,
    MIN_MINIMUM_POOL_PCT_BPS,
    REPORTING_FREQUENCIES,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_STATE_REGULATOR,
    ROLE_SYSTEM_OPERATOR,
    UNIT_TYPES,
)
from errors import fail
from response import list_response, record_response
from services import state

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------- custodians
@bp.post("/custodians")
def create_custodian():
    mw.authorize(ROLE_STATE_REGULATOR)
    body = mw.body_json()
    name = mw.req_text(body, "name")
    custodian_type = mw.req_enum(body, "custodian_type", CUSTODIAN_TYPES)
    tri_party_capable = mw.opt_bool(body, "tri_party_capable", DEFAULT_TRI_PARTY_CAPABLE)
    concentration_limit_bps = mw.opt_int(
        body,
        "concentration_limit_bps",
        default=DEFAULT_CONCENTRATION_LIMIT_BPS,
        minimum=MIN_CONCENTRATION_LIMIT_BPS,
        maximum=MAX_CONCENTRATION_LIMIT_BPS,
    )
    record = db.new_record(
        {
            "name": name,
            "custodian_type": custodian_type,
            "tri_party_capable": tri_party_capable,
            "concentration_limit_bps": concentration_limit_bps,
            "approval_status": "PENDING_APPROVAL",
            "approved_at": None,
        }
    )
    db.insert("custodians", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.post("/custodians/<custodian_id>/approve")
def approve_custodian(custodian_id):
    mw.authorize(ROLE_STATE_REGULATOR)
    custodian = mw.resolve("custodians", custodian_id)
    if custodian["approval_status"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_STATE")
    custodian["approval_status"] = "APPROVED"
    custodian["approved_at"] = db.now_ts()
    db.touch(custodian)
    state.recompute_all()
    return record_response(custodian)


@bp.get("/custodians/<custodian_id>")
def read_custodian(custodian_id):
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_CUSTODIAN,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_SYSTEM_OPERATOR,
    )
    return record_response(mw.resolve("custodians", custodian_id))


# ------------------------------------------------------- pooled programs
@bp.post("/pooled-programs")
def create_pooled_program():
    mw.authorize(ROLE_STATE_REGULATOR)
    body = mw.body_json()
    name = mw.req_text(body, "name")
    administrator_state = mw.req_text(body, "administrator_state")
    minimum_pool_pct_bps = mw.opt_int(
        body,
        "minimum_pool_pct_bps",
        default=DEFAULT_MINIMUM_POOL_PCT_BPS,
        minimum=MIN_MINIMUM_POOL_PCT_BPS,
        maximum=MAX_MINIMUM_POOL_PCT_BPS,
    )
    record = db.new_record(
        {
            "name": name,
            "administrator_state": administrator_state,
            "minimum_pool_pct_bps": minimum_pool_pct_bps,
            "aggregate_required_collateral_cents": 0,
            "aggregate_collateral_value_cents": 0,
            "unallocated_collateral_cents": 0,
            "participant_account_count": 0,
            "pool_posture": "ADEQUATE",
        }
    )
    db.insert("pooled_programs", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/pooled-programs/<program_id>")
def read_pooled_program(program_id):
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_SYSTEM_OPERATOR,
    )
    return record_response(mw.resolve("pooled_programs", program_id))


@bp.get("/pooled-programs/<program_id>/depositories")
def list_pool_depositories(program_id):
    mw.authorize(
        ROLE_STATE_REGULATOR, ROLE_BANK_COLLATERAL_OFFICER, ROLE_PUBLIC_UNIT_TREASURER
    )
    program = mw.resolve("pooled_programs", program_id)
    limit, offset = mw.page_params()
    approval_status = mw.query_filter("approval_status", DEPOSITORY_APPROVAL_STATUSES)
    members = [
        d for d in db.rows("depositories") if d["pooled_program_id"] == program["id"]
    ]
    if approval_status is not None:
        members = [d for d in members if d["approval_status"] == approval_status]
    return list_response(mw.paginate(members, limit, offset), limit, offset, len(members))


# ---------------------------------------------------------------- public units
@bp.post("/public-units")
def create_public_unit():
    mw.authorize(ROLE_STATE_REGULATOR)
    body = mw.body_json()
    name = mw.req_text(body, "name")
    unit_type = mw.req_enum(body, "unit_type", UNIT_TYPES)
    jurisdiction_state = mw.req_text(body, "jurisdiction_state")
    statutory_max_deposit_cents = mw.req_int(body, "statutory_max_deposit_cents")
    preference = mw.opt_enum(
        body, "collateral_program_preference", COLLATERAL_PROGRAM_PREFERENCES, "DEDICATED"
    )
    reporting_frequency = mw.opt_enum(
        body, "reporting_frequency", REPORTING_FREQUENCIES, "MONTHLY"
    )
    record = db.new_record(
        {
            "name": name,
            "unit_type": unit_type,
            "jurisdiction_state": jurisdiction_state,
            "collateral_program_preference": preference,
            "statutory_max_deposit_cents": statutory_max_deposit_cents,
            "reporting_frequency": reporting_frequency,
            "total_deposit_balance_cents": 0,
            "total_uninsured_cents": 0,
            "exposure_status": "NORMAL",
        }
    )
    db.insert("public_units", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/public-units/<unit_id>")
def read_public_unit(unit_id):
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_SYSTEM_OPERATOR,
    )
    return record_response(mw.resolve("public_units", unit_id))
