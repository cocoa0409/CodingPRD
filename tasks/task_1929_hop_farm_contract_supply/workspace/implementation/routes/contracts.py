"""Contract endpoints (PRD §3.5)."""

from flask import Blueprint

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_CONTRACT_MANAGER
from response import success_object
from util import (
    get_body, check_unknown_fields, req_str, req_int, req_num, req_enum, opt_int, opt_num,
)
from errors import invalid_state, stale_version
from services.core import (
    base_record, touch, public, get_contract, cancel_allocation, VARIETIES,
)

bp = Blueprint("contracts", __name__)

CM = [ROLE_CONTRACT_MANAGER]

CREATE_FIELDS = {
    "brewery_name", "variety", "term_start_year", "term_end_year",
    "annual_volume_lbs", "base_price_cents_per_lb", "alpha_floor_pct",
    "alpha_premium_cents_per_point", "alpha_discount_cents_per_point",
}

AMENDABLE_FIELDS = {
    "annual_volume_lbs", "base_price_cents_per_lb", "alpha_floor_pct",
    "alpha_premium_cents_per_point", "alpha_discount_cents_per_point",
}


@bp.route("/api/contracts", methods=["POST"])
def create_contract():
    require_roles(CM)
    body = get_body()
    check_unknown_fields(body, CREATE_FIELDS)
    brewery_name = req_str(body, "brewery_name")
    variety = req_enum(body, "variety", VARIETIES)
    term_start_year = req_int(body, "term_start_year")
    term_end_year = req_int(body, "term_end_year")
    annual_volume_lbs = req_int(body, "annual_volume_lbs", min_v=1)
    base_price = req_int(body, "base_price_cents_per_lb", min_v=1)
    alpha_floor_pct = req_num(body, "alpha_floor_pct", gt=0)
    premium = req_int(body, "alpha_premium_cents_per_point", min_v=0)
    discount = req_int(body, "alpha_discount_cents_per_point", min_v=0)
    if term_end_year < term_start_year:
        from errors import invalid_request
        raise invalid_request("term_end_year must be >= term_start_year")

    rec = base_record()
    rec.update({
        "brewery_name": brewery_name,
        "variety": variety,
        "term_start_year": term_start_year,
        "term_end_year": term_end_year,
        "annual_volume_lbs": annual_volume_lbs,
        "base_price_cents_per_lb": base_price,
        "alpha_floor_pct": alpha_floor_pct,
        "alpha_premium_cents_per_point": premium,
        "alpha_discount_cents_per_point": discount,
        "consecutive_shortfall_years": 0,
        "status": "DRAFT",
    })
    store.contracts[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/api/contracts/<contract_id>", methods=["GET"])
def get_contract_endpoint(contract_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_contract(contract_id)))


@bp.route("/api/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    contract = get_contract(contract_id)
    if contract["status"] != "DRAFT":
        raise invalid_state("Contract is not DRAFT")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(public(contract))


@bp.route("/api/contracts/<contract_id>/suspend", methods=["POST"])
def suspend_contract(contract_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    contract = get_contract(contract_id)
    if contract["status"] != "ACTIVE":
        raise invalid_state("Contract is not ACTIVE")
    # non-destructive gate: no allocation state changes; confirm/deliver are
    # rejected with ERR_CONTRACT_NOT_ACTIVE while the contract is SUSPENDED
    contract["status"] = "SUSPENDED"
    touch(contract)
    return success_object(public(contract))


@bp.route("/api/contracts/<contract_id>/reinstate", methods=["POST"])
def reinstate_contract(contract_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    contract = get_contract(contract_id)
    if contract["status"] != "SUSPENDED":
        raise invalid_state("Contract is not SUSPENDED")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(public(contract))


@bp.route("/api/contracts/<contract_id>/amendments", methods=["POST"])
def amend_contract(contract_id):
    require_roles(CM)
    body = get_body()
    check_unknown_fields(body, AMENDABLE_FIELDS | {"expected_contract_version"})
    expected = body.get("expected_contract_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        from errors import invalid_request
        raise invalid_request("expected_contract_version is required and must be an integer")
    changes = {
        "annual_volume_lbs": opt_int(body, "annual_volume_lbs", min_v=1),
        "base_price_cents_per_lb": opt_int(body, "base_price_cents_per_lb", min_v=1),
        "alpha_floor_pct": opt_num(body, "alpha_floor_pct", gt=0),
        "alpha_premium_cents_per_point": opt_int(body, "alpha_premium_cents_per_point", min_v=0),
        "alpha_discount_cents_per_point": opt_int(body, "alpha_discount_cents_per_point", min_v=0),
    }

    contract = get_contract(contract_id)
    # priority 6: from-state before the priority-7 OCC check
    if contract["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise invalid_state("Contract cannot be amended in its current state")
    if expected != contract["version"]:
        raise stale_version("expected_contract_version does not match the current version")

    for field, value in changes.items():
        if value is not None:
            contract[field] = value
    touch(contract)
    return success_object(public(contract))


@bp.route("/api/contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    contract = get_contract(contract_id)
    if contract["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise invalid_state("Contract cannot be terminated in its current state")
    contract["status"] = "TERMINATED"
    touch(contract)
    # unwind open commitments: PROJECTED/CONFIRMED/DELIVERED -> CANCELLED.
    # Confirmed allocations release their reserved lots; delivered allocations
    # keep delivered_lbs/delivered_lot_ids and do NOT release their lots.
    for alloc in list(store.allocations.values()):
        if alloc["contract_id"] != contract["id"]:
            continue
        if alloc["status"] in ("PROJECTED", "CONFIRMED", "DELIVERED"):
            cancel_allocation(alloc)
    return success_object(public(contract))
