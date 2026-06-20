"""RebalanceOrder endpoints: create, execute (buy/redeem), cancel (PRD 3.4)."""
from flask import Blueprint, request

from db import db, common_create_fields, touch, LOCK
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import calc, serialize
from services.accounts import recompute_account, post_ledger
from services.lookup import (
    get_or_404, require_string, require_positive_int, optional_string,
    optional_nonneg_int, filtered_sorted,
)

bp = Blueprint("rebalance", __name__)

READ_ROLES = {"SponsorAdmin", "DonorAdvisor"}


@bp.post("/daf/rebalance-orders")
def create_order():
    user_id, role = get_identity()
    require_role(role, {"DonorAdvisor"})
    body = get_json_body()
    donor_account_id = require_string(body, "donor_account_id")
    # amount_cents must be positive (PRD 3.4).
    amount_cents = require_positive_int(body, "amount_cents")
    source_pool_id = optional_string(body, "source_pool_id", None)
    target_pool_id = optional_string(body, "target_pool_id", None)
    target_pct_bps = optional_nonneg_int(body, "target_pct_bps", 0)

    with LOCK:
        # Body FK existence, left-to-right: account, then source pool, then target pool.
        get_or_404(db.accounts, donor_account_id)
        if source_pool_id is not None:
            get_or_404(db.pools, source_pool_id)
        if target_pool_id is not None:
            get_or_404(db.pools, target_pool_id)
        order = common_create_fields()
        order.update({
            "donor_account_id": donor_account_id,
            "source_pool_id": source_pool_id,
            "target_pool_id": target_pool_id,
            "amount_cents": amount_cents,
            "target_pct_bps": target_pct_bps,
            "source_units_redeemed_micro": 0,
            "target_units_bought_micro": 0,
            "status": "DRAFT",
        })
        db.rebalance_orders[order["id"]] = order
    return object_response(serialize.rebalance_order(order), status=201)


@bp.get("/daf/rebalance-orders/<order_id>")
def get_order(order_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    order = get_or_404(db.rebalance_orders, order_id)
    return object_response(serialize.rebalance_order(order))


@bp.get("/daf/rebalance-orders")
def list_orders():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.rebalance_orders, {
        "donor_account_id": request.args.get("donor_account_id"),
        "status": request.args.get("status"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.rebalance_order(o) for o in page], meta)


@bp.post("/daf/rebalance-orders/<order_id>/execute")
def execute_order(order_id):
    user_id, role = get_identity()
    require_role(role, {"DonorAdvisor"})
    with LOCK:
        order = get_or_404(db.rebalance_orders, order_id)
        account = db.accounts[order["donor_account_id"]]
        # Owner-scope precedes state (PRD 3.10).
        if user_id != account["primary_advisor_user_id"]:
            raise err("ERR_NOT_ACCOUNT_OWNER")
        if order["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE")

        amount = order["amount_cents"]
        source_pool_id = order["source_pool_id"]
        target_pool_id = order["target_pool_id"]

        if source_pool_id is None:
            # BUY (cash -> pool). Target pool must be OPEN; cash must cover amount.
            pool = db.pools[target_pool_id]
            if pool["status"] != "OPEN":
                raise err("ERR_POOL_CLOSED")
            if account["cash_balance_cents"] < amount:
                raise err("ERR_INSUFFICIENT_CASH")
            units = calc.units_bought_micro(amount, pool["nav_per_unit_cents"])
            alloc = _get_or_create_allocation(account, target_pool_id, order["target_pct_bps"])
            alloc["units_micro"] += units
            touch(alloc)
            account["cash_balance_cents"] -= amount
            order["target_units_bought_micro"] = units
            post_ledger(account, "POOL_BUY", -amount, "RebalanceOrder", order_id)
        else:
            # REDEEM-to-cash (pool -> cash). Source allocation value must cover amount.
            pool = db.pools[source_pool_id]
            alloc = _find_active_allocation(account["id"], source_pool_id)
            alloc_value = 0
            if alloc is not None:
                alloc_value = calc.allocation_value_cents(alloc["units_micro"], pool["nav_per_unit_cents"])
            if alloc is None or alloc_value < amount:
                raise err("ERR_INSUFFICIENT_POOL_UNITS")
            units = calc.units_redeemed_micro(amount, pool["nav_per_unit_cents"])
            alloc["units_micro"] -= units
            if alloc["units_micro"] <= 0:
                alloc["units_micro"] = max(alloc["units_micro"], 0)
            if alloc["units_micro"] == 0:
                alloc["status"] = "LIQUIDATED"
            touch(alloc)
            account["cash_balance_cents"] += amount
            order["source_units_redeemed_micro"] = units
            post_ledger(account, "POOL_REDEEM", amount, "RebalanceOrder", order_id)

        order["status"] = "EXECUTED"
        touch(order)
        recompute_account(account)
        touch(account)
    return object_response(serialize.rebalance_order(order))


@bp.post("/daf/rebalance-orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = get_identity()
    require_role(role, {"DonorAdvisor"})
    with LOCK:
        order = get_or_404(db.rebalance_orders, order_id)
        account = db.accounts[order["donor_account_id"]]
        if user_id != account["primary_advisor_user_id"]:
            raise err("ERR_NOT_ACCOUNT_OWNER")
        if order["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE")
        order["status"] = "CANCELLED"  # no balance change (PRD 3.4)
        touch(order)
    return object_response(serialize.rebalance_order(order))


def _find_active_allocation(account_id, pool_id):
    candidates = [a for a in db.allocations.values()
                  if a["donor_account_id"] == account_id
                  and a["investment_pool_id"] == pool_id
                  and a["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a["_seq"])
    return candidates[0]


def _get_or_create_allocation(account, pool_id, target_pct_bps):
    """PRD 3.4: target allocation is created lazily if the account does not yet
    hold one."""
    existing = _find_active_allocation(account["id"], pool_id)
    if existing is not None:
        return existing
    alloc = common_create_fields()
    alloc.update({
        "donor_account_id": account["id"],
        "investment_pool_id": pool_id,
        "units_micro": 0,
        "target_pct_bps": target_pct_bps,
        "status": "ACTIVE",
    })
    db.allocations[alloc["id"]] = alloc
    return alloc
