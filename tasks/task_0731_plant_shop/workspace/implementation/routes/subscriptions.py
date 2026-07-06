"""Subscriptions and the scheduler-fulfill endpoint."""
from datetime import timedelta
from flask import Blueprint, request
from clock import iso_now, get_now, parse_iso, format_iso
from db import DB
from errors import (
    not_found, unauthorized, invalid_request,
    ApiError, ERR_SUBSCRIPTION_INACTIVE,
)
from middleware import (
    auth_context, require_role, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, created, ok_list
from services.common import stamp_common, bump
from services.validation import require_fields, require_enum
from services.inventory import recompute_available_count

bp = Blueprint("subscriptions", __name__)

PLAN_TIERS = {"STARTER", "CLASSIC", "CURATOR"}
CARE_TAGS = {"EASY", "MODERATE", "EXPERT"}
LIGHT_TAGS = {"LOW", "MEDIUM", "BRIGHT_INDIRECT", "DIRECT"}
SUB_STATUSES = {"ACTIVE", "PAUSED", "CANCELLED", "MISSING_STOCK"}
MONTHLY_FEE_CENTS = {"STARTER": 2500, "CLASSIC": 4500, "CURATOR": 8000}
PLAN_PRICE_CEILING = {"STARTER": 3000, "CLASSIC": 6000, "CURATOR": 15000}


@bp.post("/subscriptions")
def create_subscription():
    role, user_id = auth_context()
    require_role(role, {"Customer"})
    payload = require_json()
    require_fields(payload, ["customer_id", "plan_tier", "care_tag_preference", "light_tag_preference"])
    cid = payload["customer_id"]
    if user_id != cid:
        raise unauthorized("Customer may only subscribe for self")
    customer = DB.customers.get(cid)
    if not customer:
        raise not_found("Customer")
    require_enum(payload["plan_tier"], PLAN_TIERS, "plan_tier")
    require_enum(payload["care_tag_preference"], CARE_TAGS, "care_tag_preference")
    require_enum(payload["light_tag_preference"], LIGHT_TAGS, "light_tag_preference")
    next_ft = get_now() + timedelta(days=30)
    entity = {
        **stamp_common(full=True),
        "customer_id": cid,
        "plan_tier": payload["plan_tier"],
        "care_tag_preference": payload["care_tag_preference"],
        "light_tag_preference": payload["light_tag_preference"],
        "status": "ACTIVE",
        "next_fulfillment_at": format_iso(next_ft),
        "monthly_fee_cents": MONTHLY_FEE_CENTS[payload["plan_tier"]],
    }
    DB.subscriptions[entity["id"]] = entity
    return created(entity)


@bp.get("/subscriptions")
def list_subs():
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    limit, offset = parse_pagination(request.args)
    customer_id = request.args.get("customer_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in SUB_STATUSES:
        raise invalid_request("invalid status filter")
    rows = list(DB.subscriptions.values())
    if customer_id:
        rows = [s for s in rows if s["customer_id"] == customer_id]
    if status_f:
        rows = [s for s in rows if s["status"] == status_f]
    if role == "Customer":
        rows = [s for s in rows if s["customer_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.get("/subscriptions/<sid>")
def get_sub(sid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    sub = DB.subscriptions.get(sid)
    if not sub:
        raise not_found("Subscription")
    if role == "Customer" and user_id != sub["customer_id"]:
        raise unauthorized("not subscription owner")
    return ok(sub)


@bp.post("/subscriptions/<sid>/pause")
def pause_sub(sid):
    role, user_id = auth_context()
    require_role(role, {"Customer"})
    sub = DB.subscriptions.get(sid)
    if not sub:
        raise not_found("Subscription")
    if user_id != sub["customer_id"]:
        raise unauthorized("not subscription owner")
    if sub["status"] != "ACTIVE":
        raise ApiError(ERR_SUBSCRIPTION_INACTIVE, 409, "subscription not ACTIVE")
    sub["status"] = "PAUSED"
    bump(sub)
    return ok(sub)


@bp.post("/subscriptions/<sid>/resume")
def resume_sub(sid):
    role, user_id = auth_context()
    require_role(role, {"Customer"})
    sub = DB.subscriptions.get(sid)
    if not sub:
        raise not_found("Subscription")
    if user_id != sub["customer_id"]:
        raise unauthorized("not subscription owner")
    if sub["status"] != "PAUSED":
        raise ApiError(ERR_SUBSCRIPTION_INACTIVE, 409, "subscription not PAUSED")
    sub["status"] = "ACTIVE"
    now = get_now()
    curr = parse_iso(sub["next_fulfillment_at"])
    if curr is None or curr < now:
        sub["next_fulfillment_at"] = format_iso(now)
    bump(sub)
    return ok(sub)


@bp.post("/subscriptions/<sid>/cancel")
def cancel_sub(sid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    sub = DB.subscriptions.get(sid)
    if not sub:
        raise not_found("Subscription")
    if role == "Customer" and user_id != sub["customer_id"]:
        raise unauthorized("not subscription owner")
    if sub["status"] not in ("ACTIVE", "PAUSED", "MISSING_STOCK"):
        from errors import invalid_state
        raise invalid_state("subscription not cancellable")
    sub["status"] = "CANCELLED"
    bump(sub)
    return ok(sub)


def _select_for_subscription(sub):
    candidates = []
    for su in DB.stock_units.values():
        if su["sale_status"] != "FOR_SALE" or su["health_status"] != "HEALTHY":
            continue
        p = DB.plants.get(su["plant_id"])
        if not p:
            continue
        if p["care_tag"] != sub["care_tag_preference"]:
            continue
        if p["light_tag"] != sub["light_tag_preference"]:
            continue
        if p["unit_price_cents"] > PLAN_PRICE_CEILING[sub["plan_tier"]]:
            continue
        candidates.append(su)
    if not candidates:
        return None
    candidates.sort(key=lambda su: (su["acquisition_date"], su["created_at"]))
    return candidates[0]


@bp.post("/_scheduler/fulfill-subscriptions")
def scheduler_fulfill():
    role, _ = auth_context()
    require_role(role, {"Manager"})
    from services.loyalty import compute_accrual_points, append_ledger
    from services.pricing import delivery_fee, order_total
    now = get_now()
    processed = 0
    fulfilled = 0
    missed = 0
    for sub in list(DB.subscriptions.values()):
        if sub["status"] not in ("ACTIVE", "MISSING_STOCK"):
            continue
        nf = parse_iso(sub["next_fulfillment_at"])
        if nf is None or nf > now:
            continue
        processed += 1
        su = _select_for_subscription(sub)
        if su is None:
            if sub["status"] == "ACTIVE":
                sub["status"] = "MISSING_STOCK"
                bump(sub)
            # If already MISSING_STOCK we don't bump.
            missed += 1
            continue
        # Hit path — create Order + OrderLine.
        p = DB.plants[su["plant_id"]]
        customer = DB.customers[sub["customer_id"]]
        subtotal = p["unit_price_cents"]
        order_common = stamp_common(full=True)
        heavy_present = p["weight_class"] == "HEAVY"
        order = {
            **order_common,
            "customer_id": sub["customer_id"],
            "fulfillment_status": "PENDING",
            "payment_status": "PAID",  # auto-charge stub
            "delivery_zone": customer["delivery_zone"],
            "gift_flag": False,
            "applied_redemption_cents": 0,
            "subtotal_cents": subtotal,
            "delivery_fee_cents": delivery_fee(customer["delivery_zone"], heavy_present, False, subtotal),
            "total_cents": 0,
            "points_provisional": 0,
            "points_finalized": 0,
        }
        order["total_cents"] = order_total(subtotal, 0, order["delivery_fee_cents"])
        DB.orders[order["id"]] = order
        # Reserve the unit.
        su["sale_status"] = "RESERVED"
        bump(su)
        recompute_available_count(su["plant_id"])
        line = {
            **stamp_common(full=False),
            "order_id": order["id"],
            "plant_id": p["id"],
            "stock_unit_id": su["id"],
            "qty": 1,
            "unit_price_cents": p["unit_price_cents"],
            "line_subtotal_cents": subtotal,
            "refund_status": "NONE",
            "refund_amount_cents": 0,
            "_reserved_stock_unit_ids": [su["id"]],
            "delivered_at": None,
        }
        DB.order_lines[line["id"]] = line
        # Loyalty provisional accrual.
        tier = customer["loyalty_tier"]
        prov = compute_accrual_points(subtotal, tier)
        order["points_provisional"] = prov
        append_ledger(sub["customer_id"], order["id"], "ACCRUAL_PROVISIONAL", prov)
        # Advance subscription.
        if sub["status"] == "MISSING_STOCK":
            sub["status"] = "ACTIVE"
        new_nf = parse_iso(sub["next_fulfillment_at"]) + timedelta(days=30)
        sub["next_fulfillment_at"] = format_iso(new_nf)
        bump(sub)
        fulfilled += 1
    return ok({
        "processed_count": processed,
        "fulfilled_count": fulfilled,
        "missed_count": missed,
    })


@bp.get("/care-reminders")
def list_reminders():
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    limit, offset = parse_pagination(request.args)
    customer_id = request.args.get("customer_id")
    subscription_id = request.args.get("subscription_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in {"PENDING", "DUE", "DISMISSED"}:
        raise invalid_request("invalid status filter")
    rows = list(DB.care_reminders.values())
    now = get_now()
    for r in rows:
        # Auto-flip PENDING -> DUE when clock >= due_at.
        if r["status"] == "PENDING":
            due = parse_iso(r["due_at"])
            if due is not None and now >= due:
                r["status"] = "DUE"
                bump(r)
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if subscription_id:
        rows = [r for r in rows if r.get("subscription_id") == subscription_id]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if role == "Customer":
        rows = [r for r in rows if r["customer_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.get("/care-reminders/<rid>")
def get_reminder(rid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    r = DB.care_reminders.get(rid)
    if not r:
        raise not_found("CareReminder")
    if role == "Customer" and user_id != r["customer_id"]:
        raise unauthorized("not reminder owner")
    if r["status"] == "PENDING":
        due = parse_iso(r["due_at"])
        if due is not None and get_now() >= due:
            r["status"] = "DUE"
            bump(r)
    return ok(r)
