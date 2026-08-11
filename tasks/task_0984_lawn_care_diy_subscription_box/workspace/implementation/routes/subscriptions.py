from datetime import timedelta

from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_CUSTOMER_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_SUBSCRIPTION_NOT_FOUND,
    ERR_CUSTOMER_SUSPENDED, ERR_PLAN_NOT_ACTIVE_FOR_SUBSCRIPTION,
    ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_SUBSCRIPTION_NOT_PAUSED,
    ERR_SUBSCRIPTION_ALREADY_CANCELLED, ERR_SKIP_ALLOWANCE_EXHAUSTED,
    ERR_NO_SKIPPABLE_SHIPMENT, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_MISMATCH,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_subscription
from services import (
    lock_plan_discount, pause_cascade, resume_cascade, cancel_cascade,
    earliest_scheduled_box, MAX_SKIPS_PER_WINDOW, SKIP_WINDOW_DAYS,
)
from util import req_str, req_enum, opt_bool, parse_dt, fmt_dt3

bp = Blueprint("subscriptions", __name__)

READ_ROLES = ["Customer", "Agronomist", "FulfillmentOps", "PlatformAdmin"]


def _get_sub_or_404(sid):
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise_err(ERR_SUBSCRIPTION_NOT_FOUND, "Subscription not found")
    return sub


@bp.route("/api/subscriptions", methods=["POST"])
def create_subscription():
    body = get_body()
    customer_id = req_str(body, "customer_id")
    plan_id = req_str(body, "plan_id")
    billing_cycle = req_enum(body, "billing_cycle", {"MONTHLY", "ANNUAL"})
    auto_ship = opt_bool(body, "auto_ship")
    if auto_ship is None:
        auto_ship = True
    next_ship_raw = body.get("next_ship_date")
    next_ship_date = None
    if next_ship_raw is not None:
        next_ship_date = parse_dt(next_ship_raw, "next_ship_date")
    if auto_ship and next_ship_date is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Field 'next_ship_date' is required when auto_ship is true")

    uid, role = authenticate(["Customer"])
    check_ownership(uid, role, customer_id)
    cust = store.customers.get(customer_id)
    if cust is None:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_err(ERR_PLAN_NOT_FOUND, "Plan not found")
    lawn = store.lawns.get(plan.lawn_id)
    if lawn is None or lawn.customer_id != customer_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Plan does not belong to the customer's lawn")
    if cust.status == "SUSPENDED":
        raise_err(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED; creates are blocked")
    if plan.status != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE_FOR_SUBSCRIPTION,
                  "Subscription creation requires an ACTIVE plan")

    ts = now()
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        customer_id=customer_id, plan_id=plan_id, billing_cycle=billing_cycle,
        auto_ship=auto_ship, status="ACTIVE",
        next_ship_date=next_ship_date, skips_used_in_window=0, skip_window_anchor=None,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    if next_ship_date is not None and next_ship_raw is not None:
        rec.raw["next_ship_date"] = next_ship_raw
    store.subscriptions[rec.id] = rec
    lock_plan_discount(plan, billing_cycle)
    return ok(ser_subscription(rec), 201)


@bp.route("/api/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_sub_or_404(sid)
    check_ownership(uid, role, rec.customer_id)
    return ok(ser_subscription(rec))


@bp.route("/api/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = authenticate(READ_ROLES)
    items = list(store.subscriptions.values())
    if role == "Customer":
        items = [s for s in items if s.customer_id == uid]
    for param in ("customer_id", "plan_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if getattr(s, param) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_subscription(s) for s in page], total, limit, offset)


@bp.route("/api/subscriptions/<sid>", methods=["PATCH"])
def patch_subscription(sid):
    body = get_body()
    auto_ship = opt_bool(body, "auto_ship")
    billing_cycle = body.get("billing_cycle")
    if billing_cycle is not None:
        req_enum(body, "billing_cycle", {"MONTHLY", "ANNUAL"})
    next_ship_raw = body.get("next_ship_date")
    next_ship_date = None
    if next_ship_raw is not None:
        next_ship_date = parse_dt(next_ship_raw, "next_ship_date")
    if "expected_subscription_version" not in body:
        raise_err(ERR_INVALID_REQUEST, "Field 'expected_subscription_version' is required")
    expected = body["expected_subscription_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "Field 'expected_subscription_version' must be an integer")

    uid, role = authenticate(["Customer"])
    rec = _get_sub_or_404(sid)
    check_ownership(uid, role, rec.customer_id)
    if expected != rec.version:
        raise_err(ERR_STALE_VERSION,
                  "expected_subscription_version does not match the subscription's current version")

    new_auto_ship = rec.auto_ship if auto_ship is None else auto_ship
    new_next_ship = rec.next_ship_date if next_ship_raw is None else next_ship_date
    if new_auto_ship and new_next_ship is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Field 'next_ship_date' is required when auto_ship is true")

    if auto_ship is not None:
        rec.auto_ship = auto_ship
    if next_ship_raw is not None:
        rec.next_ship_date = next_ship_date
        rec.raw["next_ship_date"] = next_ship_raw
    if billing_cycle is not None and billing_cycle != rec.billing_cycle:
        rec.billing_cycle = billing_cycle
        plan = store.plans.get(rec.plan_id)
        if plan is not None:
            lock_plan_discount(plan, billing_cycle)
    touch(rec)
    return ok(ser_subscription(rec))


@bp.route("/api/subscriptions/<sid>/status", methods=["POST"])
def set_status(sid):
    body = get_body()
    to_status = req_enum(body, "to_status", {"ACTIVE", "PAUSED"})
    uid, role = authenticate(["Customer"])
    rec = _get_sub_or_404(sid)
    check_ownership(uid, role, rec.customer_id)

    if to_status == "PAUSED":
        if rec.status != "ACTIVE":
            raise_err(ERR_SUBSCRIPTION_NOT_ACTIVE, "Pause requires subscription ACTIVE")
        rec.status = "PAUSED"
        pause_cascade(rec)
    else:
        if rec.status != "PAUSED":
            raise_err(ERR_SUBSCRIPTION_NOT_PAUSED, "Resume requires subscription PAUSED")
        rec.status = "ACTIVE"
        resume_cascade(rec)
    touch(rec)
    return ok(ser_subscription(rec))


@bp.route("/api/subscriptions/<sid>/skip-next-shipment", methods=["POST"])
def skip_next_shipment(sid):
    uid, role = authenticate(["Customer"])
    rec = _get_sub_or_404(sid)
    check_ownership(uid, role, rec.customer_id)

    # skip_allowance_calc: rolling 365-day window, re-anchor on expiry
    if rec.skip_window_anchor is None or now() >= rec.skip_window_anchor + timedelta(days=SKIP_WINDOW_DAYS):
        rec.skips_used_in_window = 0
        rec.skip_window_anchor = now()
        rec.raw["skip_window_anchor"] = fmt_dt3(rec.skip_window_anchor)
    if rec.skips_used_in_window >= MAX_SKIPS_PER_WINDOW:
        raise_err(ERR_SKIP_ALLOWANCE_EXHAUSTED,
                  "3 skips already used in the current rolling 365-day window")
    box = earliest_scheduled_box(sid)
    if box is None:
        raise_err(ERR_NO_SKIPPABLE_SHIPMENT, "No SCHEDULED box exists to skip")

    rec.skips_used_in_window += 1
    box.fulfillment_status = "SKIPPED"
    touch(box)
    touch(rec)
    return ok(ser_subscription(rec))


@bp.route("/api/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = authenticate(["Customer"])
    rec = _get_sub_or_404(sid)
    check_ownership(uid, role, rec.customer_id)
    if rec.status == "CANCELLED":
        raise_err(ERR_SUBSCRIPTION_ALREADY_CANCELLED, "Subscription is already CANCELLED")
    rec.status = "CANCELLED"
    cancel_cascade(rec)
    touch(rec)
    return ok(ser_subscription(rec))
