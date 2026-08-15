"""Cloth Diaper & Linen Route Service API — Flask entry point.

Implements every endpoint declared in PRD.md. Storage is in-memory dicts
only; no entity data is seeded at startup. The logical clock starts at
2026-08-01T00:00:00Z per the PRD's Logical Clock section.

Routes are split across this module (catalog, customers, subscriptions,
pauses, kits) and app_routes.py (routes, stops, intakes, wash batches,
swaps, cases, invoices, clock), which exposes a Flask Blueprint registered
below. The blueprint split keeps `python3 app.py` on a single app object.
"""

import os
from datetime import timedelta

from flask import Flask, request

import errors
import helpers as H
from db import db, new_resource, touch, clock_today
from envelope import ok, error_body
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e.error_id, e.status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_body(errors.ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_body(errors.ERR_INVALID_REQUEST, 405, "Method not allowed")


@app.errorhandler(500)
def handle_500(e):
    return error_body(errors.ERR_INVALID_REQUEST, 500, "Internal server error")


def _q(name):
    return request.args.get(name)


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------

@app.post("/api/subscription-plans")
def create_plan():
    body = H.parse_body()
    tier_code = H.req_str(body, "tier_code")
    weekly_quota = H.req_int(body, "weekly_quota", lo=1)
    weekly_fee_cents = H.req_int(body, "weekly_fee_cents", lo=0)
    overage_rate_cents = H.req_int(body, "overage_rate_cents", lo=0)
    overage_cap_items = H.opt_int(body, "overage_cap_items", 20, lo=0)
    deposit_cents = H.req_int(body, "deposit_cents", lo=0)
    service_bags_per_week = H.opt_int(body, "service_bags_per_week", 1, lo=1)
    weight_policy = H.req_enum(body, "weight_policy", {"COUNT_BASIS", "WEIGHT_BASIS"})
    kit_reserve_pct = H.opt_int(body, "kit_reserve_pct", 10, lo=0, hi=100)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    for p in db["subscription_plans"].values():
        if p["tier_code"] == tier_code:
            raise errors.bad_request("tier_code must be unique")
    plan = new_resource({
        "tier_code": tier_code,
        "weekly_quota": weekly_quota,
        "weekly_fee_cents": weekly_fee_cents,
        "overage_rate_cents": overage_rate_cents,
        "overage_cap_items": overage_cap_items,
        "deposit_cents": deposit_cents,
        "service_bags_per_week": service_bags_per_week,
        "weight_policy": weight_policy,
        "kit_reserve_pct": kit_reserve_pct,
    })
    db["subscription_plans"][plan["id"]] = plan
    return ok(H.serialize("subscription_plans", plan), 201)


@app.get("/api/subscription-plans")
def list_plans():
    return H.do_list("subscription_plans", [("tier_code", _q("tier_code"))])


@app.get("/api/subscription-plans/<plan_id>")
def get_plan(plan_id):
    return H.do_get_one("subscription_plans", plan_id)


# ---------------------------------------------------------------------------
# ServiceZone
# ---------------------------------------------------------------------------

@app.post("/api/service-zones")
def create_zone():
    body = H.parse_body()
    zone_code = H.req_str(body, "zone_code")
    weekdays = body.get("service_weekdays")
    if (not isinstance(weekdays, list) or len(weekdays) < 1 or len(weekdays) > 6
            or len(set(weekdays)) != len(weekdays)
            or any(not isinstance(w, str) or w not in H.WEEKDAYS for w in weekdays)):
        raise errors.bad_request(
            "service_weekdays must be 1..6 distinct entries of MON,TUE,WED,THU,FRI,SAT,SUN")
    stop_cutoff_hours = H.opt_int(body, "stop_cutoff_hours", 24, lo=0)
    active = H.opt_bool(body, "active", True)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    for z in db["service_zones"].values():
        if z["zone_code"] == zone_code:
            raise errors.bad_request("zone_code must be unique")
    zone = new_resource({
        "zone_code": zone_code,
        "service_weekdays": list(weekdays),
        "service_days_per_week": len(weekdays),
        "stop_cutoff_hours": stop_cutoff_hours,
        "active": active,
    })
    db["service_zones"][zone["id"]] = zone
    return ok(H.serialize("service_zones", zone), 201)


@app.get("/api/service-zones")
def list_zones():
    active_raw = _q("active")
    active = None
    if active_raw is not None:
        if active_raw.lower() == "true":
            active = True
        elif active_raw.lower() == "false":
            active = False
    return H.do_list("service_zones", [("zone_code", _q("zone_code")), ("active", active)])


@app.get("/api/service-zones/<zone_id>")
def get_zone(zone_id):
    return H.do_get_one("service_zones", zone_id)


# ---------------------------------------------------------------------------
# InventoryPool
# ---------------------------------------------------------------------------

@app.post("/api/inventory-pools")
def create_pool():
    body = H.parse_body()
    size_code = H.req_enum(body, "size_code", set(H.SIZES))
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    for p in db["inventory_pools"].values():
        if p["size_code"] == size_code:
            raise errors.bad_request("size_code must be unique across pools")
    pool = new_resource({
        "size_code": size_code,
        "on_hand_units": 0,
        "reserved_units": 0,
        "in_transit_units": 0,
        "checked_out_units": 0,
        "in_wash_units": 0,
        "quarantined_units": 0,
        "lost_units": 0,
        "retired_units": 0,
        "total_acquired_units": 0,
    })
    db["inventory_pools"][pool["id"]] = pool
    return ok(H.serialize("inventory_pools", pool), 201)


@app.get("/api/inventory-pools")
def list_pools():
    return H.do_list("inventory_pools", [("size_code", _q("size_code"))])


@app.get("/api/inventory-pools/<pool_id>")
def get_pool(pool_id):
    return H.do_get_one("inventory_pools", pool_id)


@app.post("/api/inventory-pools/<pool_id>/adjustments")
def pool_adjustment(pool_id):
    body = H.parse_body()
    adjustment_type = H.req_enum(body, "adjustment_type", {"ACQUIRE", "RETIRE"})
    units = H.req_int(body, "units", lo=1)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin", "PlantOperator"})
    pool = H.get_or_404("inventory_pools", pool_id)
    if adjustment_type == "ACQUIRE":
        pool["on_hand_units"] += units
        pool["total_acquired_units"] += units
    else:
        if pool["on_hand_units"] < units:
            raise ApiError(errors.ERR_INVENTORY_SHORTFALL, 409,
                           "On-hand units are insufficient for the RETIRE adjustment")
        pool["on_hand_units"] -= units
        pool["retired_units"] += units
    touch(pool)
    return ok(H.serialize("inventory_pools", pool))


# ---------------------------------------------------------------------------
# WashFormula
# ---------------------------------------------------------------------------

@app.post("/api/wash-formulas")
def create_formula():
    body = H.parse_body()
    formula_code = H.req_str(body, "formula_code")
    base_detergent_ml_per_kg = H.req_int(body, "base_detergent_ml_per_kg")
    sanitizer_ml_per_kg = H.req_int(body, "sanitizer_ml_per_kg")
    min_temp_celsius = H.req_int(body, "min_temp_celsius")
    min_dwell_seconds = H.req_int(body, "min_dwell_seconds")
    chlorine_ppm_min = H.req_int(body, "chlorine_ppm_min")
    chlorine_ppm_max = H.req_int(body, "chlorine_ppm_max")
    max_rewash_count = H.opt_int(body, "max_rewash_count", 2, lo=0)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    for f in db["wash_formulas"].values():
        if f["formula_code"] == formula_code:
            raise errors.bad_request("formula_code must be unique")
    formula = new_resource({
        "formula_code": formula_code,
        "base_detergent_ml_per_kg": base_detergent_ml_per_kg,
        "sanitizer_ml_per_kg": sanitizer_ml_per_kg,
        "min_temp_celsius": min_temp_celsius,
        "min_dwell_seconds": min_dwell_seconds,
        "chlorine_ppm_min": chlorine_ppm_min,
        "chlorine_ppm_max": chlorine_ppm_max,
        "max_rewash_count": max_rewash_count,
    })
    db["wash_formulas"][formula["id"]] = formula
    return ok(H.serialize("wash_formulas", formula), 201)


@app.get("/api/wash-formulas")
def list_formulas():
    return H.do_list("wash_formulas", [("formula_code", _q("formula_code"))])


@app.get("/api/wash-formulas/<formula_id>")
def get_formula(formula_id):
    return H.do_get_one("wash_formulas", formula_id)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

@app.post("/api/customers")
def create_customer():
    body = H.parse_body()
    full_name = H.req_str(body, "full_name")
    email = H.req_str(body, "email")
    service_zone_id = H.req_str(body, "service_zone_id")
    child_birthdate = H.req_date(body, "child_birthdate")
    child_size_code = H.req_enum(body, "child_size_code", set(H.SIZES))
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    H.ref_or_404("service_zones", service_zone_id)
    for c in db["customers"].values():
        if c["email"] == email:
            raise errors.bad_request("email must be unique")
    customer = new_resource({
        "full_name": full_name,
        "email": email,
        "service_zone_id": service_zone_id,
        "child_birthdate": child_birthdate.isoformat(),
        "child_size_code": child_size_code,
        "status": "ONBOARDING",
        "deposit_charged_cents": 0,
        "deposit_held_cents": 0,
        "deposit_applied_cents": 0,
        "deposit_refunded_cents": 0,
    })
    db["customers"][customer["id"]] = customer
    return ok(H.serialize("customers", customer), 201)


@app.get("/api/customers")
def list_customers():
    return H.do_list("customers", [("service_zone_id", _q("service_zone_id")),
                                   ("status", _q("status"))])


@app.get("/api/customers/<customer_id>")
def get_customer(customer_id):
    return H.do_get_one("customers", customer_id)


@app.post("/api/customers/<customer_id>/events")
def customer_event(customer_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.CUSTOMER_EVENT_TYPES)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    customer = H.get_or_404("customers", customer_id)
    if customer["status"] == "CLOSED":
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Customer is CLOSED")
    if event_type == "ACTIVATE":
        if customer["status"] != "ONBOARDING":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Customer is not ONBOARDING")
        has_pending = any(
            s["customer_id"] == customer_id and s["service_status"] == "PENDING_START"
            for s in db["subscriptions"].values())
        if not has_pending:
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Customer owns no subscription in PENDING_START")
        customer["status"] = "ACTIVE"
        touch(customer)
    elif event_type == "SUSPEND":
        if customer["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Customer is not ACTIVE")
        customer["status"] = "SUSPENDED"
        touch(customer)
        _suspend_customer_subscriptions(customer)
    elif event_type == "REINSTATE":
        if customer["status"] != "SUSPENDED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Customer is not SUSPENDED")
        customer["status"] = "ACTIVE"
        touch(customer)
        for sub in db["subscriptions"].values():
            if sub["customer_id"] == customer_id and sub["service_status"] == "SUSPENDED":
                sub["service_status"] = "ACTIVE"
                touch(sub)
    elif event_type == "CLOSE":
        if customer["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Customer can only be closed from ACTIVE or SUSPENDED")
        open_subs = [s for s in db["subscriptions"].values()
                     if s["customer_id"] == customer_id and s["service_status"] != "TERMINATED"]
        if open_subs:
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "All subscriptions must be TERMINATED before closing the customer")
        customer["status"] = "CLOSED"
        touch(customer)
    return ok(H.serialize("customers", customer))


def _suspend_customer_subscriptions(customer):
    for sub in db["subscriptions"].values():
        if sub["customer_id"] == customer["id"] and sub["service_status"] == "ACTIVE":
            sub["service_status"] = "SUSPENDED"
            touch(sub)
            for stop in db["route_stops"].values():
                if stop["subscription_id"] == sub["id"] and stop["status"] == "PLANNED":
                    H.skip_stop(stop)


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

@app.post("/api/subscriptions")
def create_subscription():
    body = H.parse_body()
    customer_id = H.req_str(body, "customer_id")
    subscription_plan_id = H.req_str(body, "subscription_plan_id")
    service_zone_id = H.req_str(body, "service_zone_id")
    start_date = H.req_date(body, "start_date")
    current_size_code = H.req_enum(body, "current_size_code", set(H.SIZES))
    window_start = H.req_int(body, "window_start_minutes", lo=0, hi=1439)
    window_end = H.req_int(body, "window_end_minutes", lo=1, hi=1440)
    if window_start >= window_end:
        raise errors.bad_request("window_start_minutes must be before window_end_minutes")
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin"})
    customer = H.ref_or_404("customers", customer_id)
    plan = H.ref_or_404("subscription_plans", subscription_plan_id)
    zone = H.ref_or_404("service_zones", service_zone_id)
    # Business checks in declared order (PRD §3.2).
    for s in db["subscriptions"].values():
        if (s["customer_id"] == customer_id
                and s["service_status"] in ("PENDING_START", "ACTIVE", "PAUSED", "SUSPENDED")):
            raise ApiError(errors.ERR_DUPLICATE_ACTIVE_SUBSCRIPTION, 409,
                           "Customer already holds a non-terminated subscription")
    if not zone["active"] or service_zone_id != customer["service_zone_id"]:
        raise ApiError(errors.ERR_ZONE_NOT_SERVICEABLE, 422,
                       "Zone is inactive or differs from the customer's home zone")
    item_count = H.kit_item_count(plan)
    pool = H.pool_for_size(current_size_code)
    if pool is None or H.available_units(pool) < item_count:
        raise ApiError(errors.ERR_INVENTORY_SHORTFALL, 409,
                       "Size pool has insufficient available units for the starter kit")
    sub = new_resource({
        "customer_id": customer_id,
        "subscription_plan_id": subscription_plan_id,
        "service_zone_id": service_zone_id,
        "start_date": start_date.isoformat(),
        "current_size_code": current_size_code,
        "window_start_minutes": window_start,
        "window_end_minutes": window_end,
        "service_status": "PENDING_START",
        "billing_status": "CURRENT",
        "missed_stop_count": 0,
        "_start_date": start_date,
    })
    db["subscriptions"][sub["id"]] = sub
    kit = new_resource({
        "subscription_id": sub["id"],
        "size_code": current_size_code,
        "item_count": item_count,
        "items_returned_count": 0,
        "status": "RESERVED",
    })
    db["starter_kits"][kit["id"]] = kit
    pool["on_hand_units"] -= item_count
    pool["reserved_units"] += item_count
    touch(pool)
    customer["deposit_charged_cents"] += plan["deposit_cents"]
    customer["deposit_held_cents"] += plan["deposit_cents"]
    touch(customer)
    return ok(H.serialize("subscriptions", sub), 201)


@app.get("/api/subscriptions")
def list_subscriptions():
    return H.do_list("subscriptions", [("customer_id", _q("customer_id")),
                                       ("subscription_plan_id", _q("subscription_plan_id")),
                                       ("service_zone_id", _q("service_zone_id")),
                                       ("service_status", _q("service_status"))])


@app.get("/api/subscriptions/<subscription_id>")
def get_subscription(subscription_id):
    return H.do_get_one("subscriptions", subscription_id)


@app.post("/api/subscriptions/<subscription_id>/events")
def subscription_event(subscription_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.SUBSCRIPTION_EVENT_TYPES)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin", "Customer"})
    if role == "Customer" and event_type != "TERMINATE":
        raise ApiError(errors.ERR_FORBIDDEN, 403,
                       "Customer may only TERMINATE their own subscription")
    sub = db["subscriptions"].get(subscription_id)
    if role == "Customer":
        H.customer_owns_or_forbid(role, uid, H.chain_customer_id("subscriptions", sub))
    if sub is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Subscription not found")
    if sub["service_status"] in H.SUB_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Subscription is TERMINATED")

    if event_type == "ACTIVATE":
        if sub["service_status"] != "PENDING_START":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Subscription is not PENDING_START")
        customer = db["customers"].get(sub["customer_id"])
        if customer is None or customer["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Customer is not ACTIVE")
        kit = H.kit_for_subscription(subscription_id)
        if kit is None or kit["status"] != "ISSUED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Starter kit is not ISSUED")
        if sub["_start_date"] > clock_today():
            raise ApiError(errors.ERR_CUTOFF_PASSED, 422,
                           "Subscription start_date is after the current logical date")
        sub["service_status"] = "ACTIVE"
        touch(sub)
    elif event_type == "SUSPEND_SERVICE":
        if sub["service_status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Subscription is not ACTIVE")
        sub["service_status"] = "SUSPENDED"
        touch(sub)
        for stop in db["route_stops"].values():
            if stop["subscription_id"] == subscription_id and stop["status"] == "PLANNED":
                H.skip_stop(stop)
    elif event_type == "RESUME_SERVICE":
        if sub["service_status"] != "SUSPENDED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Subscription is not SUSPENDED")
        sub["service_status"] = "ACTIVE"
        touch(sub)
    elif event_type == "TERMINATE":
        if sub["service_status"] not in ("ACTIVE", "PAUSED", "SUSPENDED"):
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Subscription cannot be terminated from its current state")
        # PRD §3.2 pinned order: kit, then unpaid invoices, then PLANNED stops.
        kit = H.kit_for_subscription(subscription_id)
        if kit is None or kit["status"] != "SETTLED":
            raise ApiError(errors.ERR_KIT_NOT_RETURNED, 409, "Starter kit is not SETTLED")
        for inv in db["invoices"].values():
            if inv["subscription_id"] == subscription_id and inv["status"] in ("ISSUED", "PAST_DUE"):
                raise ApiError(errors.ERR_INVOICE_UNPAID, 402,
                               "Subscription has an ISSUED or PAST_DUE invoice")
        if sub["service_status"] in ("ACTIVE", "PAUSED"):
            for stop in db["route_stops"].values():
                if stop["subscription_id"] == subscription_id and stop["status"] == "PLANNED":
                    raise ApiError(errors.ERR_INVALID_STATE, 409,
                                   "Subscription still has PLANNED route stops")
        if sub["service_status"] == "PAUSED":
            for pause in db["service_pauses"].values():
                if pause["subscription_id"] == subscription_id and pause["status"] == "ACTIVE":
                    plan = db["subscription_plans"].get(sub["subscription_plan_id"])
                    zone = db["service_zones"].get(sub["service_zone_id"])
                    pause["status"] = "COMPLETED"
                    if plan is not None and zone is not None:
                        pause["final_credit_cents"] = H.pause_final_credit_cents(pause, plan, zone)
                    touch(pause)
        sub["service_status"] = "TERMINATED"
        touch(sub)
        # deposit_refund_settlement (PRD §2.8)
        customer = db["customers"].get(sub["customer_id"])
        if customer is not None:
            refund = customer["deposit_held_cents"]
            customer["deposit_held_cents"] = 0
            customer["deposit_refunded_cents"] += refund
            touch(customer)
    return ok(H.serialize("subscriptions", sub))


# ---------------------------------------------------------------------------
# ServicePause
# ---------------------------------------------------------------------------

@app.post("/api/service-pauses")
def create_pause():
    body = H.parse_body()
    subscription_id = H.req_str(body, "subscription_id")
    start_date = H.req_date(body, "start_date")
    end_date = H.req_date(body, "end_date")
    expected_subscription_version = H.req_int(body, "expected_subscription_version")
    uid, role = H.actor()
    H.require_role(role, {"Customer", "PlatformAdmin"})
    sub = db["subscriptions"].get(subscription_id)
    if role == "Customer":
        H.customer_owns_or_forbid(role, uid, H.chain_customer_id("subscriptions", sub))
    if sub is None:
        raise ApiError(errors.ERR_REFERENCE_NOT_FOUND, 404,
                       "Referenced subscription_id does not exist")
    if expected_subscription_version != sub["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_subscription_version does not match the subscription version")
    today = clock_today()
    if start_date < today + timedelta(days=H.MIN_NOTICE_DAYS):
        raise ApiError(errors.ERR_PAUSE_NOTICE_TOO_SHORT, 422,
                       "Pause start_date must be at least 3 days after the current date")
    if end_date <= start_date or (end_date - start_date).days > H.MAX_PAUSE_DAYS:
        raise ApiError(errors.ERR_PAUSE_WINDOW_INVALID, 422,
                       "end_date must be after start_date and the span must not exceed 28 days")
    for p in db["service_pauses"].values():
        if p["subscription_id"] != subscription_id or p["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if start_date < p["_end_date"] and p["_start_date"] < end_date:
            raise ApiError(errors.ERR_PAUSE_OVERLAP, 409,
                           "Pause window intersects another SCHEDULED or ACTIVE pause")
    plan = db["subscription_plans"].get(sub["subscription_plan_id"])
    estimated = H.billing_weeks_touched(start_date, end_date) * plan["weekly_fee_cents"]
    pause = new_resource({
        "subscription_id": subscription_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": "SCHEDULED",
        "estimated_credit_cents": estimated,
        "final_credit_cents": None,
        "_start_date": start_date,
        "_end_date": end_date,
    })
    db["service_pauses"][pause["id"]] = pause
    touch(sub)
    return ok(H.serialize("service_pauses", pause), 201)


@app.get("/api/service-pauses")
def list_pauses():
    return H.do_list("service_pauses", [("subscription_id", _q("subscription_id")),
                                        ("status", _q("status"))])


@app.get("/api/service-pauses/<pause_id>")
def get_pause(pause_id):
    return H.do_get_one("service_pauses", pause_id)


@app.post("/api/service-pauses/<pause_id>/cancel")
def cancel_pause(pause_id):
    H.parse_body()
    uid, role = H.actor()
    H.require_role(role, {"Customer", "PlatformAdmin"})
    pause = db["service_pauses"].get(pause_id)
    if role == "Customer":
        H.customer_owns_or_forbid(role, uid, H.chain_customer_id("service_pauses", pause))
    if pause is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Service pause not found")
    if pause["status"] in H.PAUSE_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Pause is in a terminal state")
    if pause["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a SCHEDULED pause can be cancelled")
    pause["status"] = "CANCELLED"
    touch(pause)
    sub = db["subscriptions"].get(pause["subscription_id"])
    if sub is not None:
        touch(sub)
    return ok(H.serialize("service_pauses", pause))


# ---------------------------------------------------------------------------
# StarterKit
# ---------------------------------------------------------------------------

@app.get("/api/starter-kits")
def list_kits():
    return H.do_list("starter_kits", [("subscription_id", _q("subscription_id")),
                                      ("status", _q("status"))])


@app.get("/api/starter-kits/<kit_id>")
def get_kit(kit_id):
    return H.do_get_one("starter_kits", kit_id)


@app.post("/api/starter-kits/<kit_id>/events")
def kit_event(kit_id):
    body = H.parse_body()
    event_type = H.req_enum(body, "event_type", H.KIT_EVENT_TYPES)
    items_returned_count = None
    if event_type == "RETURN":
        items_returned_count = H.req_int(body, "items_returned_count", lo=0)
    uid, role = H.actor()
    H.require_role(role, {"PlatformAdmin", "PlantOperator"})
    kit = H.get_or_404("starter_kits", kit_id)
    if kit["status"] in H.KIT_TERMINAL:
        raise ApiError(errors.ERR_ALREADY_TERMINAL, 409, "Starter kit is SETTLED")

    if event_type == "ISSUE":
        if kit["status"] != "RESERVED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Kit is not RESERVED")
        pool = H.pool_for_size(kit["size_code"])
        if pool is not None:
            pool["reserved_units"] -= kit["item_count"]
            pool["checked_out_units"] += kit["item_count"]
            touch(pool)
        kit["status"] = "ISSUED"
        touch(kit)
    elif event_type == "RETURN":
        if kit["status"] != "ISSUED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Kit is not ISSUED")
        if items_returned_count > kit["item_count"]:
            raise ApiError(errors.ERR_RETURN_COUNT_MISMATCH, 422,
                           "items_returned_count exceeds the kit item_count")
        pool = H.pool_for_size(kit["size_code"])
        shortage = kit["item_count"] - items_returned_count
        if pool is not None:
            pool["checked_out_units"] -= items_returned_count
            pool["in_wash_units"] += items_returned_count
        kit["items_returned_count"] = items_returned_count
        kit["status"] = "RETURNED"
        touch(kit)
        if shortage > 0:
            H.auto_lost_case(kit["subscription_id"],
                             pool["id"] if pool is not None else None,
                             kit["size_code"], shortage, kit["created_at"][:10])
            if pool is not None:
                pool["checked_out_units"] -= shortage
                pool["lost_units"] += shortage
        if pool is not None:
            touch(pool)
    elif event_type == "SETTLE":
        if kit["status"] != "RETURNED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Kit is not RETURNED")
        for case in db["lost_item_cases"].values():
            if (case["subscription_id"] == kit["subscription_id"]
                    and case["status"] not in ("SETTLED", "WAIVED")):
                raise ApiError(errors.ERR_INVALID_STATE, 409,
                               "Every lost-item case of the subscription must be SETTLED or WAIVED")
        kit["status"] = "SETTLED"
        touch(kit)
    return ok(H.serialize("starter_kits", kit))


# ---------------------------------------------------------------------------
# Remaining routes live in app_routes.py (blueprint).
# ---------------------------------------------------------------------------

from app_routes import bp as _routes_bp  # noqa: E402

app.register_blueprint(_routes_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
