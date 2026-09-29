"""Collateral inventory, pricing and pledge allocations (PRD 3.4)."""

from flask import Blueprint

import db
import middleware as mw
from constants import (
    ALLOCATION_STATUSES,
    ASSET_TYPES,
    DEFAULT_MARKET_PRICE_BPS,
    ELIGIBILITY_STATUSES,
    NEVER_PLEDGEABLE_ASSET_TYPES,
    PLEDGE_STATUSES,
    PRICE_STALE_HOURS,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_STATE_REGULATOR,
    ROLE_SYSTEM_OPERATOR,
)
from errors import fail
from response import list_response, record_response
from services import calc, state

bp = Blueprint("collateral", __name__)

ASSET_READ_ROLES = (
    ROLE_STATE_REGULATOR,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_SYSTEM_OPERATOR,
)
ALLOCATION_READ_ROLES = (
    ROLE_STATE_REGULATOR,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_SYSTEM_OPERATOR,
)


def pledgeable(asset):
    """Rung 13: the state accepts the type and the asset is still eligible."""
    if asset["asset_type"] in NEVER_PLEDGEABLE_ASSET_TYPES:
        return False
    return asset["eligibility_status"] == "ELIGIBLE"


def price_is_stale(asset):
    return calc.hours_stale(asset["priced_at"]) > PRICE_STALE_HOURS


@bp.post("/collateral-assets")
def register_asset():
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    body = mw.body_json()
    depository = mw.resolve_fk("depositories", body.get("depository_id"))
    custodian = mw.resolve_fk("custodians", body.get("custodian_id"))
    mw.req_id(body, "depository_id")
    mw.req_id(body, "custodian_id")
    cusip = mw.req_text(body, "cusip")
    asset_type = mw.req_enum(body, "asset_type", ASSET_TYPES)
    par_value_cents = mw.req_int(body, "par_value_cents")
    market_price_bps = mw.opt_int(body, "market_price_bps", default=DEFAULT_MARKET_PRICE_BPS)
    if depository["approval_status"] != "APPROVED":
        fail("ERR_DEPOSITORY_NOT_APPROVED")
    for existing in state.assets_of_depository(depository["id"]):
        if existing["cusip"] == cusip:
            fail("ERR_DUPLICATE_IDENTIFIER")
    haircut_bps = calc.haircut_for(asset_type)
    market_value_cents = calc.market_value(par_value_cents, market_price_bps)
    record = db.new_record(
        {
            "depository_id": depository["id"],
            "custodian_id": custodian["id"],
            "cusip": cusip,
            "asset_type": asset_type,
            "par_value_cents": par_value_cents,
            "market_price_bps": market_price_bps,
            "priced_at": db.now_ts(),
            "haircut_bps": haircut_bps,
            "market_value_cents": market_value_cents,
            "collateral_value_cents": calc.scale_bps(market_value_cents, 10000 - haircut_bps),
            "pledged_par_cents": 0,
            "available_par_cents": par_value_cents,
            "eligibility_status": "ELIGIBLE",
            "pledge_status": "UNPLEDGED",
            "ineligible_reason": None,
        }
    )
    db.insert("collateral_assets", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/collateral-assets/<asset_id>")
def read_asset(asset_id):
    mw.authorize(*ASSET_READ_ROLES)
    return record_response(mw.resolve("collateral_assets", asset_id))


@bp.get("/collateral-assets")
def list_assets():
    mw.authorize(*ASSET_READ_ROLES)
    limit, offset = mw.page_params()
    depository_id = mw.query_filter("depository_id")
    custodian_id = mw.query_filter("custodian_id")
    asset_type = mw.query_filter("asset_type", ASSET_TYPES)
    eligibility_status = mw.query_filter("eligibility_status", ELIGIBILITY_STATUSES)
    pledge_status = mw.query_filter("pledge_status", PLEDGE_STATUSES)
    records = db.rows("collateral_assets")
    if depository_id is not None:
        records = [r for r in records if r["depository_id"] == depository_id]
    if custodian_id is not None:
        records = [r for r in records if r["custodian_id"] == custodian_id]
    if asset_type is not None:
        records = [r for r in records if r["asset_type"] == asset_type]
    if eligibility_status is not None:
        records = [r for r in records if r["eligibility_status"] == eligibility_status]
    if pledge_status is not None:
        records = [r for r in records if r["pledge_status"] == pledge_status]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/collateral-assets/<asset_id>/prices")
def post_price(asset_id):
    mw.authorize(ROLE_SYSTEM_OPERATOR, ROLE_BANK_COLLATERAL_OFFICER)
    asset = mw.resolve("collateral_assets", asset_id)
    body = mw.body_json()
    market_price_bps = mw.req_int(body, "market_price_bps")
    if asset["eligibility_status"] != "ELIGIBLE":
        fail("ERR_INVALID_STATE")
    asset["market_price_bps"] = market_price_bps
    asset["priced_at"] = db.now_ts()
    state.recompute_all(apply_status=True)
    db.touch(asset)
    return record_response(asset)


@bp.post("/collateral-assets/<asset_id>/mark-ineligible")
def mark_ineligible(asset_id):
    mw.authorize(ROLE_STATE_REGULATOR)
    asset = mw.resolve("collateral_assets", asset_id)
    body = mw.body_json()
    reason = mw.req_text(body, "ineligible_reason")
    if asset["eligibility_status"] != "ELIGIBLE":
        fail("ERR_INVALID_STATE")
    asset["eligibility_status"] = "INELIGIBLE"
    asset["ineligible_reason"] = reason
    asset["collateral_value_cents"] = 0
    db.touch(asset)
    for allocation in state.allocations_of_asset(asset["id"]):
        if allocation["status"] == "ACTIVE":
            state.release_allocation(allocation, "ASSET_INELIGIBLE")
    state.recompute_all(apply_status=True)
    return record_response(asset)


# ----------------------------------------------------------- pledge allocations
@bp.post("/pledge-allocations")
def create_allocation():
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    body = mw.body_json()
    agreement = mw.resolve_fk("pledge_agreements", body.get("pledge_agreement_id"))
    asset = mw.resolve_fk("collateral_assets", body.get("collateral_asset_id"))
    mw.req_id(body, "pledge_agreement_id")
    mw.req_id(body, "collateral_asset_id")
    allocated_par = mw.req_int(body, "allocated_par_cents")
    effective_from = mw.req_ts(body, "effective_from")
    effective_to = mw.opt_ts(body, "effective_to", db.SENTINEL_TS)
    expected = mw.req_version(body, "expected_pledge_agreement_version")
    if expected != agreement["version"]:
        fail("ERR_STALE_AGREEMENT_VERSION")
    depository = db.get("depositories", agreement["depository_id"])
    if depository is None or depository["approval_status"] != "APPROVED":
        fail("ERR_DEPOSITORY_NOT_APPROVED")
    if agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_NOT_EXECUTED")
    if not pledgeable(asset):
        fail("ERR_COLLATERAL_TYPE_INELIGIBLE")
    if asset["custodian_id"] != agreement["custodian_id"]:
        fail("ERR_CUSTODIAN_MISMATCH")
    if asset["depository_id"] != agreement["depository_id"]:
        fail("ERR_DEPOSITORY_MISMATCH")
    if price_is_stale(asset):
        fail("ERR_STALE_COLLATERAL_PRICE")
    if effective_from.dt >= effective_to.dt:
        fail("ERR_INVALID_INTERVAL")
    if agreement["executed_at"] is None or effective_from.dt < agreement["executed_at"].dt:
        fail("ERR_INVALID_INTERVAL")
    if not state.par_capacity_available(asset, effective_from.dt, effective_to.dt, allocated_par):
        fail("ERR_ALLOCATION_OVERSUBSCRIBED")
    incoming_value = calc.asset_value_of_par(asset, allocated_par)
    custodian = db.get("custodians", agreement["custodian_id"])
    at_custodian = (
        state.collateral_value_at_custodian(depository["id"], agreement["custodian_id"])
        + incoming_value
    )
    depository_total = depository["total_pledged_collateral_value_cents"] + incoming_value
    if custodian is not None:
        if at_custodian * 10000 > depository_total * custodian["concentration_limit_bps"]:
            fail("ERR_CUSTODIAN_CONCENTRATION_EXCEEDED")
    if depository["total_pledged_par_cents"] + allocated_par > depository[
        "approved_pledge_capacity_cents"
    ]:
        fail("ERR_PLEDGE_CAPACITY_EXCEEDED")
    record = db.new_record(
        {
            "pledge_agreement_id": agreement["id"],
            "collateral_asset_id": asset["id"],
            "allocated_par_cents": allocated_par,
            "allocated_collateral_value_cents": incoming_value,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "ACTIVE",
            "released_at": None,
            "release_reason": None,
            "created_by_substitution_id": None,
        }
    )
    db.insert("pledge_allocations", record)
    db.touch(agreement)
    state.recompute_all(apply_status=True)
    return record_response(record, 201)


@bp.get("/pledge-allocations/<allocation_id>")
def read_allocation(allocation_id):
    mw.authorize(*ALLOCATION_READ_ROLES)
    return record_response(mw.resolve("pledge_allocations", allocation_id))


@bp.get("/pledge-allocations")
def list_allocations():
    mw.authorize(*ALLOCATION_READ_ROLES)
    limit, offset = mw.page_params()
    agreement_id = mw.query_filter("pledge_agreement_id")
    asset_id = mw.query_filter("collateral_asset_id")
    substitution_id = mw.query_filter("created_by_substitution_id")
    status_filter = mw.query_filter("status", ALLOCATION_STATUSES)
    records = db.rows("pledge_allocations")
    if agreement_id is not None:
        records = [r for r in records if r["pledge_agreement_id"] == agreement_id]
    if asset_id is not None:
        records = [r for r in records if r["collateral_asset_id"] == asset_id]
    if substitution_id is not None:
        records = [r for r in records if r["created_by_substitution_id"] == substitution_id]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/pledge-allocations/<allocation_id>/release")
def release(allocation_id):
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    allocation = mw.resolve("pledge_allocations", allocation_id)
    if allocation["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    agreement = db.get("pledge_agreements", allocation["pledge_agreement_id"])
    if agreement is None or agreement["status"] != "EXECUTED":
        fail("ERR_INVALID_STATE")
    if state.has_inflight_substitution_for_allocation(allocation["id"]):
        fail("ERR_INVALID_STATE")
    state.release_allocation(allocation, "OFFICER_RELEASE")
    state.recompute_all(apply_status=True)
    return record_response(allocation)
