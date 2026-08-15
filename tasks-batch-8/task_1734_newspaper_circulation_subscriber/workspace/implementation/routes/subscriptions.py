"""Subscription endpoints plus nested vacation-hold and save-offer creation."""
from flask import Blueprint, request

import domain
from db import bump, by_created, create_rec, store
from errors import ApiError
from middleware import body, own_check, require_roles
from response import ok_obj, paginate
from serialize import ser_hold, ser_save_offer, ser_subscription
from util import days
from validate import req_date, req_decimal, req_int, req_str

bp = Blueprint("subscriptions", __name__)


@bp.post("/api/subscriptions")
def create_subscription():
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    b = body()
    # Ownership (priority 3) precedes existence (4) for the subscriber chain.
    if role == "Subscriber" and b.get("subscriber_id") is not None:
        own_check(uid, role, b.get("subscriber_id"))
    subscriber_id = req_str(b, "subscriber_id")
    plan_id = req_str(b, "plan_id")
    subr = domain.fetch(store.subscribers, subscriber_id)
    plan = domain.fetch(store.plans, plan_id)
    start_date = req_date(b, "start_date")
    # State: plan must be ACTIVE.
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED", 409, "Plan is RETIRED")
    # Referential: print-capable plan requires a service address.
    if domain.print_capable(plan) and not subr["service_address"]:
        raise ApiError("ERR_SERVICE_ADDRESS_REQUIRED", 409,
                       "Print-capable plan requires subscriber.service_address")
    rec = create_rec(store.subscriptions, {
        "subscriber_id": subr["id"],
        "plan_id": plan["id"],
        "start_date": start_date,
        "billing_status": "PENDING_START",
        "delivery_status": "NOT_DELIVERED",
        "next_charge_date": None,
        "pending_plan_id": None,
        "pending_plan_effective_date": None,
        "save_discount_pct": None,
        "save_discount_until": None,
        "cancel_reason": None,
        "ended_at": None,
    })
    # Bubble-up: creating a subscription rescues a LAPSED subscriber.
    if subr["status"] == "LAPSED":
        subr["status"] = "ACTIVE"
        bump(subr)
    return ok_obj(ser_subscription(rec), 201)


@bp.get("/api/subscriptions")
def list_subscriptions():
    require_roles("ServiceRep", "DistrictManager", "CirculationDirector")
    recs = by_created(store.subscriptions.values())
    for param in ("subscriber_id", "plan_id", "pending_plan_id",
                  "billing_status", "delivery_status"):
        v = request.args.get(param)
        if v is not None:
            recs = [s for s in recs if s[param] == v]
    return paginate(recs, ser_subscription)


@bp.get("/api/subscriptions/<sid>")
def get_subscription(sid):
    uid, role = require_roles("Subscriber", "ServiceRep", "DistrictManager",
                              "CirculationDirector")
    sub = domain.fetch(store.subscriptions, sid)
    own_check(uid, role, sub["subscriber_id"])
    return ok_obj(ser_subscription(sub))


@bp.post("/api/subscriptions/<sid>/plan-change")
def plan_change(sid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    sub = domain.fetch(store.subscriptions, sid)
    own_check(uid, role, sub["subscriber_id"])
    b = body()
    new_plan_id = req_str(b, "new_plan_id")
    effective_date = req_date(b, "effective_date")
    expected_version = req_int(b, "expected_subscription_version")
    # An effective_date already arrived or passed is a shape violation.
    if effective_date <= domain.today():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "effective_date must be in the future")
    new_plan = domain.fetch(store.plans, new_plan_id)
    # State: subscription must be non-terminal; target plan must be ACTIVE.
    if sub["billing_status"] not in domain.NON_TERMINAL:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Subscription is in a terminal billing state")
    if new_plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED", 409, "Target plan is RETIRED")
    # OCC (priority 7).
    if expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_subscription_version does not match Subscription.version")
    # Referential: print-capable target requires a service address.
    subr = domain.subscriber_of(sub)
    if domain.print_capable(new_plan) and not subr["service_address"]:
        raise ApiError("ERR_SERVICE_ADDRESS_REQUIRED", 409,
                       "Print-capable target plan requires subscriber.service_address")
    # Supersede: silently replaces any previously staged change.
    sub["pending_plan_id"] = new_plan["id"]
    sub["pending_plan_effective_date"] = effective_date
    bump(sub)
    return ok_obj(ser_subscription(sub))


@bp.post("/api/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    sub = domain.fetch(store.subscriptions, sid)
    own_check(uid, role, sub["subscriber_id"])
    b = body()
    reason = req_str(b, "reason")
    t = domain.today()
    if sub["billing_status"] in ("ACTIVE", "GRACE"):
        # Move to CANCEL_PENDING and auto-create the CANCEL_FLOW save offer.
        sub["billing_status"] = "CANCEL_PENDING"
        sub["cancel_reason"] = reason
        bump(sub)
        create_rec(store.save_offers, {
            "subscription_id": sub["id"],
            "offer_type": "DISCOUNT_RATE",
            "discount_pct": 0.25,
            "duration_weeks": 8,
            "origin": "CANCEL_FLOW",
            "status": "OFFERED",
            "expires_at": t + days(7),
        })
    elif sub["billing_status"] == "SUSPENDED":
        # No save offer from SUSPENDED: direct churn.
        sub["cancel_reason"] = reason
        domain.cancel_terminal(sub)
    else:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Cancel requires billing_status in ACTIVE, GRACE or SUSPENDED")
    return ok_obj(ser_subscription(sub))


# --- VacationHold creation (nested under subscription) ----------------------

@bp.post("/api/subscriptions/<sid>/vacation-holds")
def create_hold(sid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    sub = domain.fetch(store.subscriptions, sid)
    own_check(uid, role, sub["subscriber_id"])
    b = body()
    start_date = req_date(b, "start_date")
    end_date = req_date(b, "end_date")
    resolution = req_str(b, "resolution")
    if resolution not in ("CREDIT", "REDELIVER"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "resolution must be CREDIT or REDELIVER")
    length = (end_date - start_date).days
    if length < 1 or length > 21:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Hold length (end_date - start_date) must be 1..21 days")
    # State: billing axis must be in the active set.
    if sub["billing_status"] not in domain.ACTIVE_SET:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Hold requires billing_status ACTIVE or GRACE")
    # Temporal: start not in the past; half-open overlap vs SCHEDULED/ACTIVE.
    t = domain.today()
    if start_date < t:
        raise ApiError("ERR_HOLD_WINDOW_INVALID", 409,
                       "Hold start_date is in the past")
    for h in store.holds.values():
        if h["subscription_id"] != sub["id"]:
            continue
        if h["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        # Half-open [start, end) intersection; adjacency is allowed.
        if start_date < h["end_date"] and h["start_date"] < end_date:
            raise ApiError("ERR_HOLD_OVERLAP", 409,
                           "Hold overlaps an existing SCHEDULED/ACTIVE hold")
    # Referential: holds are meaningful for print-capable plans only.
    if not domain.print_capable(domain.plan_of(sub)):
        raise ApiError("ERR_DIGITAL_ONLY_PLAN", 409,
                       "Vacation holds require a print-capable plan")
    # Fiscal: annual 30-day hold budget (per calendar year of the new hold).
    if domain.annual_hold_days_used(sub["id"], start_date.year) + length > \
            domain.ANNUAL_HOLD_BUDGET_DAYS:
        raise ApiError("ERR_HOLD_LIMIT_EXCEEDED", 409,
                       "Annual 30-day hold budget would be exceeded")
    rec = create_rec(store.holds, {
        "subscription_id": sub["id"],
        "start_date": start_date,
        "end_date": end_date,
        "resolution": resolution,
        "status": "SCHEDULED",
        "weekly_rate_snapshot_cents": None,
        "credit_amount_cents": None,
    })
    return ok_obj(ser_hold(rec), 201)


# --- SaveOffer manual creation (nested under subscription, OCC-guarded) -----

@bp.post("/api/subscriptions/<sid>/save-offers")
def create_save_offer(sid):
    require_roles("ServiceRep", "CirculationDirector")
    sub = domain.fetch(store.subscriptions, sid)
    b = body()
    discount_pct = req_decimal(b, "discount_pct", min_v="0.10", max_v="0.50")
    duration_weeks = req_int(b, "duration_weeks", min_v=4, max_v=26)
    expected_version = req_int(b, "expected_subscription_version")
    if sub["billing_status"] not in domain.NON_TERMINAL:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Subscription is in a terminal billing state")
    if expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_subscription_version does not match Subscription.version")
    # Supersede: auto-EXPIRE any existing OFFERED offer (billing untouched).
    for offer in store.save_offers.values():
        if offer["subscription_id"] == sub["id"] and offer["status"] == "OFFERED":
            domain.expire_offer(offer, churn=False)
    rec = create_rec(store.save_offers, {
        "subscription_id": sub["id"],
        "offer_type": "DISCOUNT_RATE",
        "discount_pct": discount_pct,
        "duration_weeks": duration_weeks,
        "origin": "RETENTION_REP",
        "status": "OFFERED",
        "expires_at": domain.today() + days(7),
    })
    bump(sub)
    return ok_obj(ser_save_offer(rec), 201)
