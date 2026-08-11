"""SubscriptionPlan, MerchantAccount, BillingCycle endpoints."""

from flask import Blueprint, request

import db
from db import store, stamp, touch
from errors import ApiError, bad_request, invalid_state, already_terminal, not_found
from services import (
    TIERS, CYCLE_TERMINAL, ser_plan, ser_merchant, ser_cycle,
    get_or_404, billing_charge, cycle_fulfilled, cycle_in_flight,
)
from util import (
    require_roles, respond, body, req_str, req_int, req_bool, req_enum,
    req_dt, paginate,
)

bp = Blueprint("orgs", __name__)


def _check_ownership_merchant(uid, role, merchant_id):
    if role == "MerchantAdmin" and uid != merchant_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "MerchantAdmin may act only on its own merchant")


# ------------------------------------------------------- subscription plans --
@bp.post("/subscription-plans")
def create_plan():
    require_roles("PlatformAdmin")
    b = body(required=True)
    plan = {
        "tier": req_enum(b, "tier", TIERS),
        "monthly_fee_cents": req_int(b, "monthly_fee_cents", minimum=0),
        "included_returns": req_int(b, "included_returns", minimum=0),
        "overage_fee_cents": req_int(b, "overage_fee_cents", minimum=0),
        "pickup_enabled": req_bool(b, "pickup_enabled"),
        "boxless_enabled": req_bool(b, "boxless_enabled"),
        "oversize_enabled": req_bool(b, "oversize_enabled"),
        "free_returns": req_bool(b, "free_returns"),
        "oversize_surcharge_cents": req_int(b, "oversize_surcharge_cents", minimum=0),
        "pickup_fee_cents": req_int(b, "pickup_fee_cents", minimum=0),
        "status": "DRAFT",
    }
    stamp(plan)
    store["plans"][plan["id"]] = plan
    return respond(ser_plan(plan), 201)


@bp.get("/subscription-plans/<pid>")
def get_plan(pid):
    require_roles("PlatformAdmin", "MerchantAdmin", "SupportAgent")
    return respond(ser_plan(get_or_404("plans", pid)))


@bp.post("/subscription-plans/<pid>/publish")
def publish_plan(pid):
    require_roles("PlatformAdmin")
    plan = get_or_404("plans", pid)
    if plan["status"] == "RETIRED":
        already_terminal("Plan is RETIRED")
    if plan["status"] != "DRAFT":
        invalid_state("Only a DRAFT plan can be published")
    plan["status"] = "PUBLISHED"
    touch(plan)
    return respond(ser_plan(plan))


@bp.post("/subscription-plans/<pid>/retire")
def retire_plan(pid):
    require_roles("PlatformAdmin")
    plan = get_or_404("plans", pid)
    if plan["status"] == "RETIRED":
        already_terminal("Plan is RETIRED")
    if plan["status"] != "PUBLISHED":
        invalid_state("Only a PUBLISHED plan can be retired")
    for m in store["merchants"].values():
        if m["plan_id"] == pid and m["status"] in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_PLAN_IN_USE", 409,
                           "Plan retire blocked by ACTIVE/SUSPENDED merchants")
    plan["status"] = "RETIRED"
    touch(plan)
    return respond(ser_plan(plan))


# --------------------------------------------------------- merchant accounts -
@bp.post("/merchant-accounts")
def create_merchant():
    require_roles("PlatformAdmin")
    b = body(required=True)
    legal_name = req_str(b, "legal_name")
    plan_id = req_str(b, "plan_id")
    plan = get_or_404("plans", plan_id)
    if plan["status"] != "PUBLISHED":
        invalid_state("Plan must be PUBLISHED at merchant creation")
    merchant = {
        "legal_name": legal_name,
        "plan_id": plan_id,
        "status": "ACTIVE",
        "ledger_balance_cents": 0,
    }
    stamp(merchant)
    store["merchants"][merchant["id"]] = merchant
    return respond(ser_merchant(merchant), 201)


@bp.get("/merchant-accounts/<mid>")
def get_merchant(mid):
    uid, role = require_roles("PlatformAdmin", "MerchantAdmin", "SupportAgent")
    _check_ownership_merchant(uid, role, mid)
    return respond(ser_merchant(get_or_404("merchants", mid)))


@bp.get("/merchant-accounts")
def list_merchants():
    require_roles("PlatformAdmin", "SupportAgent")
    items = list(store["merchants"].values())
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    if plan_id is not None:
        items = [m for m in items if m["plan_id"] == plan_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, meta = paginate(items)
    return respond([ser_merchant(m) for m in page], page=meta)


@bp.post("/merchant-accounts/<mid>/suspend")
def suspend_merchant(mid):
    require_roles("PlatformAdmin")
    m = get_or_404("merchants", mid)
    if m["status"] == "CLOSED":
        already_terminal("Merchant is CLOSED")
    if m["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE merchant can be suspended")
    m["status"] = "SUSPENDED"
    touch(m)
    return respond(ser_merchant(m))


@bp.post("/merchant-accounts/<mid>/reactivate")
def reactivate_merchant(mid):
    require_roles("PlatformAdmin")
    m = get_or_404("merchants", mid)
    if m["status"] == "CLOSED":
        already_terminal("Merchant is CLOSED")
    if m["status"] != "SUSPENDED":
        invalid_state("Only a SUSPENDED merchant can be reactivated")
    m["status"] = "ACTIVE"
    touch(m)
    return respond(ser_merchant(m))


@bp.post("/merchant-accounts/<mid>/close")
def close_merchant(mid):
    require_roles("PlatformAdmin")
    m = get_or_404("merchants", mid)
    if m["status"] == "CLOSED":
        already_terminal("Merchant is CLOSED")
    for c in store["cycles"].values():
        if c["merchant_id"] == mid and c["status"] in ("OPEN", "CLOSING"):
            raise ApiError("ERR_BILLING_CYCLE_OPEN", 409,
                           "Merchant close blocked by an OPEN or CLOSING cycle")
    # Cascade: in-flight orders CANCELLED, active labels VOIDED,
    # HELD reservations RELEASED, their slots back to EMPTY.
    from services import active_label, held_reservation, release_reservation, ORDER_TERMINAL
    for o in store["orders"].values():
        if o["merchant_id"] != mid or o["status"] in ORDER_TERMINAL:
            continue
        o["status"] = "CANCELLED"
        touch(o)
        label = active_label(o)
        if label is not None:
            label["status"] = "VOIDED"
            touch(label)
        res = held_reservation(o["id"])
        if res is not None:
            release_reservation(res)
    m["status"] = "CLOSED"
    touch(m)
    return respond(ser_merchant(m))


@bp.get("/merchant-accounts/<mid>/billing-cycles")
def list_merchant_cycles(mid):
    uid, role = require_roles("PlatformAdmin", "MerchantAdmin")
    _check_ownership_merchant(uid, role, mid)
    get_or_404("merchants", mid)
    items = [c for c in store["cycles"].values() if c["merchant_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return respond([ser_cycle(c) for c in page], page=meta)


@bp.get("/merchant-accounts/<mid>/return-orders")
def list_merchant_orders(mid):
    uid, role = require_roles("PlatformAdmin", "MerchantAdmin", "SupportAgent")
    _check_ownership_merchant(uid, role, mid)
    get_or_404("merchants", mid)
    items = [o for o in store["orders"].values() if o["merchant_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(items)
    from services import ser_order
    return respond([ser_order(o) for o in page], page=meta)


@bp.post("/merchant-accounts/<mid>/billing-cycles")
def create_cycle(mid):
    require_roles("PlatformAdmin")
    get_or_404("merchants", mid)
    b = body(required=True)
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    if not period_end > period_start:
        bad_request("period_end must be strictly after period_start")
    # Half-open overlap: each window starts before the other ends.
    for c in store["cycles"].values():
        if c["merchant_id"] != mid or c["status"] in CYCLE_TERMINAL:
            continue
        if period_start < c["period_end"] and c["period_start"] < period_end:
            raise ApiError("ERR_BILLING_PERIOD_OVERLAP", 409,
                           "New cycle window overlaps an existing cycle")
    cycle = {
        "merchant_id": mid,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "fulfilled_count": None,
        "in_flight_count": None,
        "base_cents": None,
        "overage_count": None,
        "overage_fee_cents": None,
        "surcharge_cents": None,
        "gross_cents": None,
        "discount_cents": None,
        "total_cents": None,
        "closed_by_user_id": None,
        "settled_by_user_id": None,
    }
    stamp(cycle)
    store["cycles"][cycle["id"]] = cycle
    return respond(ser_cycle(cycle), 201)


# ------------------------------------------------------------ billing cycles
@bp.get("/billing-cycles/<cid>")
def get_cycle(cid):
    uid, role = require_roles("PlatformAdmin", "MerchantAdmin")
    cycle = get_or_404("cycles", cid)
    _check_ownership_merchant(uid, role, cycle["merchant_id"])
    return respond(ser_cycle(cycle))


@bp.get("/billing-cycles/<cid>/charge-preview")
def charge_preview(cid):
    uid, role = require_roles("PlatformAdmin", "MerchantAdmin")
    cycle = get_or_404("cycles", cid)
    _check_ownership_merchant(uid, role, cycle["merchant_id"])
    if cycle["status"] in CYCLE_TERMINAL:
        already_terminal("Cycle is SETTLED")
    if cycle["status"] != "OPEN":
        invalid_state("Charge preview requires an OPEN cycle")
    return respond(billing_charge(cycle, "provisional_preview"))


@bp.post("/billing-cycles/<cid>/close")
def close_cycle(cid):
    uid, _ = require_roles("PlatformAdmin")
    cycle = get_or_404("cycles", cid)
    if cycle["status"] in CYCLE_TERMINAL:
        already_terminal("Cycle is SETTLED")
    if cycle["status"] != "OPEN":
        invalid_state("Only an OPEN cycle can be closed")
    charge = billing_charge(cycle, "final_close")
    cycle["fulfilled_count"] = charge["fulfilled_count"]
    cycle["in_flight_count"] = charge["in_flight_count"]
    for k in ("base_cents", "overage_count", "overage_fee_cents", "surcharge_cents",
              "gross_cents", "discount_cents", "total_cents"):
        cycle[k] = charge[k]
    cycle["closed_by_user_id"] = uid
    cycle["status"] = "CLOSING"
    touch(cycle)
    return respond(ser_cycle(cycle))


@bp.post("/billing-cycles/<cid>/settle")
def settle_cycle(cid):
    uid, _ = require_roles("PlatformAdmin")
    cycle = get_or_404("cycles", cid)
    if cycle["status"] != "CLOSING":
        if cycle["status"] in CYCLE_TERMINAL:
            already_terminal("Cycle is SETTLED")
        invalid_state("Only a CLOSING cycle can be settled")
    if uid == cycle["closed_by_user_id"]:
        raise ApiError("ERR_SOD_SETTLER_EQUALS_CLOSER", 403,
                       "Billing settler must differ from closer")
    cycle["status"] = "SETTLED"
    cycle["settled_by_user_id"] = uid
    touch(cycle)
    merchant = store["merchants"][cycle["merchant_id"]]
    merchant["ledger_balance_cents"] += cycle["total_cents"]
    touch(merchant)
    return respond(ser_cycle(cycle))


@bp.post("/billing-cycles/<cid>/dispute")
def dispute_cycle(cid):
    uid, role = require_roles("MerchantAdmin")
    cycle = get_or_404("cycles", cid)
    _check_ownership_merchant(uid, role, cycle["merchant_id"])
    if cycle["status"] != "SETTLED":
        invalid_state("Only a SETTLED cycle can be disputed")
    cycle["status"] = "DISPUTED"
    touch(cycle)
    merchant = store["merchants"][cycle["merchant_id"]]
    merchant["ledger_balance_cents"] -= cycle["total_cents"]
    touch(merchant)
    return respond(ser_cycle(cycle))


@bp.post("/billing-cycles/<cid>/resettle")
def resettle_cycle(cid):
    uid, _ = require_roles("PlatformAdmin")
    cycle = get_or_404("cycles", cid)
    if cycle["status"] != "DISPUTED":
        invalid_state("Only a DISPUTED cycle can be re-settled")
    if uid == cycle["closed_by_user_id"]:
        raise ApiError("ERR_SOD_SETTLER_EQUALS_CLOSER", 403,
                       "Billing settler must differ from closer")
    cycle["status"] = "SETTLED"
    cycle["settled_by_user_id"] = uid
    touch(cycle)
    merchant = store["merchants"][cycle["merchant_id"]]
    merchant["ledger_balance_cents"] += cycle["total_cents"]
    touch(merchant)
    return respond(ser_cycle(cycle))
