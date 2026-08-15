"""Equipment pools and checkouts (late fees, lost declarations)."""

from flask import Blueprint, g, request

import errors as E
from domain import (pool_out, checkout_out, get_or_404, eligibility_gate,
                    equipment_late_fee, ITEM_TYPES)
from store import DB
from util import (body_json, req_str, req_int, req_enum, req_dt, envelope_object,
                  list_response, require_role, stamp_new, touch, now)

bp = Blueprint("equipment", __name__)


@bp.route("/v1/equipment-pools", methods=["POST"])
def create_pool():
    require_role("RecAdmin")
    body = body_json()
    item_type = req_enum(body, "item_type", ITEM_TYPES)
    total_qty = req_int(body, "total_qty")
    daily_fee = req_int(body, "daily_late_fee_cents")
    unit_replacement = req_int(body, "unit_replacement_cents")
    if total_qty < 1:
        raise E.err_validation("total_qty must be >= 1")
    if daily_fee < 0:
        raise E.err_validation("daily_late_fee_cents must be >= 0")
    if unit_replacement < 1:
        raise E.err_validation("unit_replacement_cents must be >= 1")
    for p in DB.equipment_pools.values():
        if p["item_type"] == item_type:
            raise E.err_validation("item_type must be unique across pools")
    pool = stamp_new({
        "item_type": item_type,
        "total_qty": total_qty,
        "daily_late_fee_cents": daily_fee,
        "unit_replacement_cents": unit_replacement,
        "available_qty": total_qty,
    })
    DB.equipment_pools[pool["id"]] = pool
    return envelope_object(pool_out(pool), 201)


@bp.route("/v1/equipment-pools/<equipment_pool_id>", methods=["GET"])
def get_pool(equipment_pool_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    pool = get_or_404(DB.equipment_pools, equipment_pool_id)
    return envelope_object(pool_out(pool))


@bp.route("/v1/equipment-pools", methods=["GET"])
def list_pools():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    item_type = request.args.get("item_type")
    records = [p for p in DB.equipment_pools.values()
               if item_type is None or p["item_type"] == item_type]
    return list_response(records, pool_out)


@bp.route("/v1/equipment-checkouts", methods=["POST"])
def create_checkout():
    require_role("Member")
    body = body_json()
    if body.get("member_id") is not None and body["member_id"] != g.user_id:
        raise E.err_forbidden("Members may only check out equipment for themselves")
    member_id = req_str(body, "member_id")
    if member_id != g.user_id:
        raise E.err_forbidden("Members may only check out equipment for themselves")
    pool_id = req_str(body, "equipment_pool_id")
    member = get_or_404(DB.members, member_id)
    pool = get_or_404(DB.equipment_pools, pool_id)
    quantity = req_int(body, "quantity")
    if quantity < 1:
        raise E.err_validation("quantity must be >= 1")
    due_at = req_dt(body, "due_at")
    if due_at <= now():
        raise E.err_validation("due_at must be strictly after the logical current time")
    eligibility_gate(member)  # suspended -> waiver -> membership
    if quantity > pool["available_qty"]:
        raise E.err_equipment_insufficient()
    # Fiscal gate runs last of all.
    if member["outstanding_fines_cents"] > 0:
        raise E.err_outstanding_fines()
    checkout = stamp_new({
        "equipment_pool_id": pool_id,
        "member_id": member_id,
        "quantity": quantity,
        "due_at": due_at,
        "status": "OUT",
        "returned_at": None,
        "late_fee_cents": None,
    })
    DB.checkouts[checkout["id"]] = checkout
    pool["available_qty"] -= quantity
    touch(pool)
    return envelope_object(checkout_out(checkout), 201)


@bp.route("/v1/equipment-checkouts/<equipment_checkout_id>", methods=["GET"])
def get_checkout(equipment_checkout_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    checkout = get_or_404(DB.checkouts, equipment_checkout_id)
    return envelope_object(checkout_out(checkout))


@bp.route("/v1/equipment-checkouts", methods=["GET"])
def list_checkouts():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    member_id = request.args.get("member_id")
    pool_id = request.args.get("equipment_pool_id")
    status = request.args.get("status")
    records = [c for c in DB.checkouts.values()
               if (member_id is None or c["member_id"] == member_id)
               and (pool_id is None or c["equipment_pool_id"] == pool_id)
               and (status is None or c["status"] == status)]
    return list_response(records, checkout_out)


@bp.route("/v1/equipment-checkouts/<equipment_checkout_id>/return", methods=["POST"])
def return_checkout(equipment_checkout_id):
    require_role("FacilityManager")
    checkout = get_or_404(DB.checkouts, equipment_checkout_id)
    if checkout["status"] != "OUT":
        raise E.err_invalid_state("Only an OUT checkout can be returned")
    pool = DB.equipment_pools.get(checkout["equipment_pool_id"])
    member = DB.members.get(checkout["member_id"])
    fee = equipment_late_fee(checkout, pool)
    checkout["status"] = "RETURNED"
    checkout["returned_at"] = now()
    checkout["late_fee_cents"] = fee
    touch(checkout)
    if pool is not None:
        pool["available_qty"] += checkout["quantity"]
        touch(pool)
    if member is not None and fee > 0:
        member["outstanding_fines_cents"] += fee
        touch(member)
    return envelope_object(checkout_out(checkout))


@bp.route("/v1/equipment-checkouts/<equipment_checkout_id>/report-lost", methods=["POST"])
def report_lost(equipment_checkout_id):
    require_role("FacilityManager")
    checkout = get_or_404(DB.checkouts, equipment_checkout_id)
    if checkout["status"] != "OUT":
        raise E.err_invalid_state("Only an OUT checkout can be declared lost")
    pool = DB.equipment_pools.get(checkout["equipment_pool_id"])
    member = DB.members.get(checkout["member_id"])
    checkout["status"] = "LOST"
    touch(checkout)
    if member is not None and pool is not None:
        member["outstanding_fines_cents"] += checkout["quantity"] * pool["unit_replacement_cents"]
        touch(member)
    if pool is not None:
        pool["total_qty"] -= checkout["quantity"]
        touch(pool)
    return envelope_object(checkout_out(checkout))
