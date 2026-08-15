"""Allocation run and allocation lifecycle endpoints (PRD §3.6)."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_CONTRACT_MANAGER
from response import success_object, success_list, parse_pagination
from util import get_body, check_unknown_fields, req_int, req_enum
from errors import (
    invalid_state, not_found, ApiError,
    ERR_CONTRACT_NOT_ACTIVE, ERR_EMPTY_DELIVERY, ERR_FINAL_TEST_REQUIRED,
)
from services.core import (
    touch, public, get_allocation,
    run_pro_rata, fifo_reserve, cancel_allocation, default_contract_cascade,
    compute_delivered_alpha, alpha_price_adjustment, filtered_sorted,
    VARIETIES, ALLOCATION_STATUSES,
)

bp = Blueprint("allocations", __name__)

CM = [ROLE_CONTRACT_MANAGER]


@bp.route("/api/allocation-runs", methods=["POST"])
def create_allocation_run():
    require_roles(CM)
    body = get_body()
    check_unknown_fields(body, {"crop_year", "variety"})
    crop_year = req_int(body, "crop_year")
    variety = req_enum(body, "variety", VARIETIES)

    available_lbs, contracted_total_lbs, created_ids = run_pro_rata(crop_year, variety)
    return success_object({
        "available_lbs": available_lbs,
        "contracted_total_lbs": contracted_total_lbs,
        "created_allocation_ids": created_ids,
    }, status=201)


@bp.route("/api/allocations/<allocation_id>", methods=["GET"])
def get_allocation_endpoint(allocation_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_allocation(allocation_id)))


@bp.route("/api/allocations", methods=["GET"])
def list_allocations():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.allocations.values()), request.args, {
        "contract_id": ("str", "contract_id"),
        "crop_year": ("int", "crop_year"),
        "status": ("enum", "status", ALLOCATION_STATUSES),
        "reserved_lot_ids": ("member", "reserved_lot_ids"),
        "delivered_lot_ids": ("member", "delivered_lot_ids"),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


def _contract_of(alloc):
    contract = store.contracts.get(alloc["contract_id"])
    if contract is None:
        raise not_found("Contract not found")
    return contract


@bp.route("/api/allocations/<allocation_id>/confirm", methods=["POST"])
def confirm_allocation(allocation_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    alloc = get_allocation(allocation_id)
    if alloc["status"] != "PROJECTED":
        raise invalid_state("Allocation is not PROJECTED")
    contract = _contract_of(alloc)
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "Contract is not ACTIVE")

    fifo_reserve(alloc, contract)
    alloc["status"] = "CONFIRMED"
    touch(alloc)
    return success_object(public(alloc))


@bp.route("/api/allocations/<allocation_id>/cancel", methods=["POST"])
def cancel_allocation_endpoint(allocation_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    alloc = get_allocation(allocation_id)
    if alloc["status"] not in ("PROJECTED", "CONFIRMED"):
        raise invalid_state("Allocation is not PROJECTED or CONFIRMED")
    cancel_allocation(alloc)
    return success_object(public(alloc))


@bp.route("/api/allocations/<allocation_id>/deliver", methods=["POST"])
def deliver_allocation(allocation_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    alloc = get_allocation(allocation_id)
    if alloc["status"] != "CONFIRMED":
        raise invalid_state("Allocation is not CONFIRMED")
    contract = _contract_of(alloc)
    # suspension bites on confirm and deliver alike (PRD §3.5)
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "Contract is not ACTIVE")
    if not alloc["reserved_lot_ids"]:
        raise ApiError(ERR_EMPTY_DELIVERY, 422, "Allocation has no reserved lots to deliver")

    reserved = [store.pellet_lots[lid] for lid in alloc["reserved_lot_ids"]
                if lid in store.pellet_lots]
    alloc["delivered_lot_ids"] = list(alloc["reserved_lot_ids"])
    alloc["delivered_lbs"] = sum(p["qty_lbs"] for p in reserved)
    for p in reserved:
        p["inventory_status"] = "DELIVERED"
        touch(p)
    alloc["delivered_alpha_pct"] = compute_delivered_alpha(reserved)
    if alloc["delivered_alpha_pct"] is not None:
        alloc["estimated_unit_price_cents"] = alpha_price_adjustment(
            Decimal(str(alloc["delivered_alpha_pct"])), contract)
    else:
        alloc["estimated_unit_price_cents"] = None
    alloc["status"] = "DELIVERED"
    touch(alloc)
    return success_object(public(alloc))


@bp.route("/api/allocations/<allocation_id>/settle", methods=["POST"])
def settle_allocation(allocation_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    alloc = get_allocation(allocation_id)
    if alloc["status"] != "DELIVERED":
        raise invalid_state("Allocation is not DELIVERED")
    contract = _contract_of(alloc)

    # every source harvest lot of every delivered pellet lot needs a final alpha
    for lid in alloc["delivered_lot_ids"]:
        pellet = store.pellet_lots.get(lid)
        if pellet is None:
            continue
        for sid in pellet["source_lot_ids"]:
            src = store.harvest_lots.get(sid)
            if src is not None and src["alpha_pct_final"] is None:
                raise ApiError(ERR_FINAL_TEST_REQUIRED, 422,
                               "A source harvest lot of a delivered pellet lot lacks a FINAL test")

    alloc["delivery_shortfall_lbs"] = alloc["allocated_lbs"] - alloc["delivered_lbs"]
    alloc["unit_price_cents"] = alpha_price_adjustment(
        Decimal(str(alloc["delivered_alpha_pct"])), contract)
    alloc["settlement_total_cents"] = alloc["delivered_lbs"] * alloc["unit_price_cents"]
    alloc["status"] = "SETTLED"
    touch(alloc)

    # shortfall memory: +1 on any shortfall, reset on a fully-delivered year;
    # reaching 2 auto-defaults the contract (one mutation event on the contract)
    if alloc["shortfall_lbs"] + alloc["delivery_shortfall_lbs"] > 0:
        contract["consecutive_shortfall_years"] += 1
    else:
        contract["consecutive_shortfall_years"] = 0
    if contract["consecutive_shortfall_years"] >= 2 and contract["status"] == "ACTIVE":
        contract["status"] = "DEFAULTED"
        touch(contract)
        default_contract_cascade(contract)
    else:
        touch(contract)

    return success_object(public(alloc))
