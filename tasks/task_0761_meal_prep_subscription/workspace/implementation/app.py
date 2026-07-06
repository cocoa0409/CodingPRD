"""Meal-Prep Subscription API — Flask entry point and routes.

In-memory only. Store is empty on every boot; no seeded entities.
"""
import os
from datetime import datetime, timedelta

from flask import Flask, request

import store
from store import db, now_clock, format_sec, format_flexible, parse_iso, parse_date, base_fields, touch
import helpers
from helpers import (
    ApiError, ok, err_response, authenticate, authorize, deny_ownership,
    get_body, require_present, require_str, as_int, as_str_array,
    read_pagination, paginate,
)
import domain

app = Flask(__name__)
app.url_map.strict_slashes = False


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return err_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return err_response("ERR_INVALID_REQUEST", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(exc):
    return err_response("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return err_response(exc.error_id, exc.http_status, exc.message)
    return err_response("ERR_INVALID_REQUEST", 500, "Internal error: %s" % exc)


# --------------------------------------------------------------------------
# Cutoff / pause helpers
# --------------------------------------------------------------------------
def compute_cutoff_at(delivery_date_str, zone):
    d = parse_date(delivery_date_str)
    cutoff_date = d - timedelta(days=zone["order_lead_days"])
    hh, mm = zone["cutoff_time_utc"].split(":")
    dt = datetime(cutoff_date.year, cutoff_date.month, cutoff_date.day, int(hh), int(mm), 0)
    return format_sec(dt)


def date_in_pause(sub_id, delivery_date_str):
    d = parse_date(delivery_date_str)
    for pw in db.pause_windows.values():
        if pw["subscription_id"] == sub_id and pw["status"] == "SCHEDULED":
            s = parse_date(pw["start_date"])
            e = parse_date(pw["end_date"])
            if s <= d < e:
                return True
    return False


# ==========================================================================
# Test-driving endpoints (/_ namespace) — PlatformAdmin
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    iso = require_present(body, "to_iso8601")
    dt = parse_iso(iso)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "to_iso8601 is not a valid ISO 8601 instant")
    db.clock = dt
    return ok({"current_utc": format_flexible(dt)})


@app.route("/_payments/simulate", methods=["POST"])
def simulate_payment():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    box_id = body.get("box_id")
    if box_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: box_id")
    box = domain.get_box(box_id)
    outcome = body.get("outcome")
    if outcome not in ("SUCCEEDED", "DECLINED"):
        raise ApiError("ERR_INVALID_ENUM", 422, "outcome must be SUCCEEDED or DECLINED")
    if box["billing_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Box billing is not PENDING")
    if outcome == "SUCCEEDED":
        box["billing_status"] = "CHARGED"
        if box["credit_applied_cents"] > 0:
            customer = domain.customer_of_box(box)
            domain.add_ledger(customer["id"], -box["credit_applied_cents"],
                              "CREDIT_APPLIED", box_id=box["id"])
        touch(box)
    else:
        box["billing_status"] = "CHARGE_FAILED"
        touch(box)
    return ok(helpers.ser_box(box))


# ==========================================================================
# Catalog config — ShippingZone / Plan / Meal
# ==========================================================================
@app.route("/shipping-zones", methods=["POST"])
def create_zone():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    zone_code = require_str(body, "zone_code")
    name = require_str(body, "name")
    requires_cold_pack = body.get("requires_cold_pack", True)
    if not isinstance(requires_cold_pack, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "requires_cold_pack must be boolean")
    base_fee = as_int(require_present(body, "base_shipping_fee_cents"), "base_shipping_fee_cents", 0)
    cold_fee = as_int(require_present(body, "cold_pack_fee_cents"), "cold_pack_fee_cents", 0)
    lead = as_int(require_present(body, "order_lead_days"), "order_lead_days", 0)
    cutoff = require_str(body, "cutoff_time_utc")
    if not _valid_hhmm(cutoff):
        raise ApiError("ERR_INVALID_REQUEST", 422, "cutoff_time_utc must be HH:MM in [00:00,23:59]")
    if any(z["zone_code"] == zone_code for z in db.zones.values()):
        raise ApiError("ERR_DUPLICATE", 422, "zone_code already exists")
    z = base_fields()
    z.update({
        "zone_code": zone_code, "name": name, "requires_cold_pack": requires_cold_pack,
        "base_shipping_fee_cents": base_fee, "cold_pack_fee_cents": cold_fee,
        "order_lead_days": lead, "cutoff_time_utc": cutoff,
    })
    db.zones[z["id"]] = z
    return ok(helpers.ser_zone(z), 201)


def _valid_hhmm(s):
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        return False
    try:
        hh = int(s[:2]); mm = int(s[3:])
    except ValueError:
        return False
    return 0 <= hh <= 23 and 0 <= mm <= 59


@app.route("/plans", methods=["POST"])
def create_plan():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    plan_code = require_str(body, "plan_code")
    name = require_str(body, "name")
    meals_per_week = as_int(require_present(body, "meals_per_week"), "meals_per_week", 1)
    price = as_int(require_present(body, "price_per_meal_cents"), "price_per_meal_cents", 1)
    if any(p["plan_code"] == plan_code for p in db.plans.values()):
        raise ApiError("ERR_DUPLICATE", 422, "plan_code already exists")
    p = base_fields()
    p.update({"plan_code": plan_code, "name": name,
              "meals_per_week": meals_per_week, "price_per_meal_cents": price})
    db.plans[p["id"]] = p
    return ok(helpers.ser_plan(p), 201)


@app.route("/meals", methods=["POST"])
def create_meal():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    meal_code = require_str(body, "meal_code")
    name = require_str(body, "name")
    protein = as_int(require_present(body, "protein_g"), "protein_g", 0)
    carb = as_int(require_present(body, "carb_g"), "carb_g", 0)
    fat = as_int(require_present(body, "fat_g"), "fat_g", 0)
    calories = as_int(require_present(body, "calories"), "calories", 0)
    allergens = as_str_array(body.get("allergens"), "allergens")
    dietary = as_str_array(body.get("dietary_tags"), "dietary_tags")
    if any(m["meal_code"] == meal_code for m in db.meals.values()):
        raise ApiError("ERR_DUPLICATE", 422, "meal_code already exists")
    m = base_fields()
    m.update({"meal_code": meal_code, "name": name, "protein_g": protein,
              "carb_g": carb, "fat_g": fat, "calories": calories,
              "allergens": allergens, "dietary_tags": dietary})
    db.meals[m["id"]] = m
    return ok(helpers.ser_meal(m), 201)


@app.route("/meals", methods=["GET"])
def list_meals():
    # Public endpoint — no authentication required.
    limit, offset = read_pagination()
    dietary_tag = request.args.get("dietary_tag")
    exclude_allergen = request.args.get("exclude_allergen")
    min_protein = request.args.get("min_protein")
    min_protein_val = None
    if min_protein is not None:
        try:
            min_protein_val = int(min_protein)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 422, "min_protein must be an integer")
    items = list(db.meals.values())
    if dietary_tag is not None:
        items = [m for m in items if dietary_tag in m["dietary_tags"]]
    if exclude_allergen is not None:
        items = [m for m in items if exclude_allergen not in m["allergens"]]
    if min_protein_val is not None:
        items = [m for m in items if m["protein_g"] >= min_protein_val]
    data, pagination = paginate(items, limit, offset, helpers.ser_meal)
    return ok(data, 200, "array", pagination)


# ==========================================================================
# ProductionRun — kitchen + par + temporal
# ==========================================================================
def _line_conflict(line_code, w_start, w_end, exclude_id=None):
    buf = timedelta(minutes=store.LINE_BUFFER_MINUTES)
    for r in db.runs.values():
        if r["id"] == exclude_id or r["line_code"] != line_code:
            continue
        if r["status"] == "CANCELLED":
            continue
        s_ex = parse_iso(r["window_start"])
        e_ex = parse_iso(r["window_end"])
        if w_start < e_ex + buf and s_ex < w_end + buf:
            return True
    return False


@app.route("/production-runs", methods=["POST"])
def create_run():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    meal_id = body.get("meal_id")
    if meal_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: meal_id")
    domain.get_meal(meal_id)
    delivery_date = require_str(body, "delivery_date")
    if parse_date(delivery_date) is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "delivery_date must be YYYY-MM-DD")
    line_code = require_str(body, "line_code")
    ws = require_present(body, "window_start")
    we = require_present(body, "window_end")
    w_start = parse_iso(ws)
    w_end = parse_iso(we)
    if w_start is None or w_end is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "window_start/window_end must be ISO 8601 instants")
    par_total = as_int(require_present(body, "par_total"), "par_total", 0)
    if _line_conflict(line_code, w_start, w_end):
        raise ApiError("ERR_LINE_CONFLICT", 409, "Production run overlaps buffer on this line")
    if w_end <= w_start:
        raise ApiError("ERR_INVALID_REQUEST", 422, "window_end must be after window_start")
    r = base_fields()
    r.update({
        "meal_id": meal_id, "delivery_date": delivery_date, "line_code": line_code,
        "window_start": ws, "window_end": we, "par_total": par_total,
        "par_reserved": 0, "par_remaining": par_total, "status": "SCHEDULED",
    })
    db.runs[r["id"]] = r
    return ok(helpers.ser_run(r), 201)


@app.route("/production-runs/<rid>/open", methods=["POST"])
def open_run(rid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    r = domain.get_run(rid)
    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Run is not SCHEDULED")
    w_start = parse_iso(r["window_start"])
    w_end = parse_iso(r["window_end"])
    if _line_conflict(r["line_code"], w_start, w_end, exclude_id=r["id"]):
        raise ApiError("ERR_LINE_CONFLICT", 409, "Production run overlaps buffer on this line")
    r["status"] = "AVAILABLE"
    touch(r)
    return ok(helpers.ser_run(r))


@app.route("/production-runs/<rid>/cancel", methods=["POST"])
def cancel_run(rid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    r = domain.get_run(rid)
    if r["status"] not in ("AVAILABLE", "SOLD_OUT"):
        raise ApiError("ERR_INVALID_STATE", 409, "Run cannot be cancelled from its current state")
    r["status"] = "CANCELLED"
    touch(r)
    # Cascade: SELECTED items on OPEN boxes -> REMOVED, release par, SWAP_CREDIT.
    for item in list(db.box_items.values()):
        if item["status"] != "SELECTED" or item.get("reserved_run_id") != r["id"]:
            continue
        box = db.boxes.get(item["box_id"])
        if box is None or box["fulfillment_status"] != "OPEN":
            continue
        item["status"] = "REMOVED"
        item["reserved_run_id"] = None
        touch(item)
        customer = domain.customer_of_box(box)
        domain.add_ledger(customer["id"], item["line_gross_cents"], "SWAP_CREDIT", box_id=box["id"])
    return ok(helpers.ser_run(r))


@app.route("/production-runs/<rid>/complete", methods=["POST"])
def complete_run(rid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    r = domain.get_run(rid)
    if r["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Run is not AVAILABLE")
    r["status"] = "COMPLETED"
    touch(r)
    return ok(helpers.ser_run(r))


@app.route("/production-runs/<rid>", methods=["GET"])
def get_run_ep(rid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    r = domain.get_run(rid)
    return ok(helpers.ser_run(r))


@app.route("/production-runs", methods=["GET"])
def list_runs():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    limit, offset = read_pagination()
    meal_id = request.args.get("meal_id")
    delivery_date = request.args.get("delivery_date")
    items = list(db.runs.values())
    if meal_id is not None:
        items = [r for r in items if r["meal_id"] == meal_id]
    if delivery_date is not None:
        items = [r for r in items if r["delivery_date"] == delivery_date]
    data, pagination = paginate(items, limit, offset, helpers.ser_run)
    return ok(data, 200, "array", pagination)


# ==========================================================================
# Customer / wallet / referral
# ==========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    # Public endpoint — no authentication required.
    body = get_body()
    zone_id = body.get("shipping_zone_id")
    if zone_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: shipping_zone_id")
    domain.get_zone(zone_id)
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    allergen_exclusions = as_str_array(body.get("allergen_exclusions"), "allergen_exclusions")
    referred_by_code = body.get("referred_by_code")
    if referred_by_code is not None and not isinstance(referred_by_code, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "referred_by_code must be a string")
    if any(c["email"] == email for c in db.customers.values()):
        raise ApiError("ERR_DUPLICATE", 422, "email already exists")
    c = base_fields()
    c.update({
        "email": email, "full_name": full_name, "shipping_zone_id": zone_id,
        "allergen_exclusions": allergen_exclusions,
        "referral_code": store.mint_referral_code(),
        "referred_by_code": referred_by_code,
        "status": "ACTIVE",
    })
    db.customers[c["id"]] = c
    # Create a PENDING referral if referred_by_code resolves to an existing code.
    if referred_by_code:
        referrer = next((x for x in db.customers.values()
                         if x["referral_code"] == referred_by_code), None)
        if referrer is not None:
            ref = base_fields()
            ref.update({
                "referrer_customer_id": referrer["id"],
                "referee_customer_id": c["id"],
                "code": referred_by_code,
                "reward_cents": 0,
                "status": "PENDING",
            })
            db.referrals[ref["id"]] = ref
    return ok(helpers.ser_customer(c), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer_ep(cid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    c = domain.get_customer(cid)
    if role == "Customer" and c["id"] != uid:
        deny_ownership()
    return ok(helpers.ser_customer(c))


@app.route("/customers", methods=["GET"])
def list_customers():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    limit, offset = read_pagination()
    zone_id = request.args.get("shipping_zone_id")
    items = list(db.customers.values())
    if zone_id is not None:
        items = [c for c in items if c["shipping_zone_id"] == zone_id]
    data, pagination = paginate(items, limit, offset, helpers.ser_customer)
    return ok(data, 200, "array", pagination)


@app.route("/customers/<cid>/credits", methods=["POST"])
def issue_credit(cid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    c = domain.get_customer(cid)
    body = get_body()
    reason = body.get("reason")
    if reason is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: reason")
    if reason not in store.LEDGER_REASONS:
        raise ApiError("ERR_INVALID_ENUM", 422, "reason is not a valid ledger reason")
    if reason != "SWAP_CREDIT":
        raise ApiError("ERR_INVALID_ENUM", 422, "reason must be SWAP_CREDIT on this endpoint")
    amount = as_int(require_present(body, "amount_cents"), "amount_cents")
    entry = domain.add_ledger(c["id"], amount, "SWAP_CREDIT", box_id=None)
    return ok(helpers.ser_ledger(entry), 201)


# ==========================================================================
# Subscription / pause / plan-change
# ==========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = authenticate()
    authorize(role, {"Customer"})
    body = get_body()
    customer_id = body.get("customer_id")
    if customer_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: customer_id")
    if customer_id != uid:
        deny_ownership()
    domain.get_customer(customer_id)
    plan_id = body.get("plan_id")
    if plan_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: plan_id")
    plan = domain.get_plan(plan_id)
    s = base_fields()
    s.update({
        "customer_id": customer_id, "plan_id": plan_id,
        "meals_per_week": plan["meals_per_week"], "status": "ACTIVE",
    })
    db.subscriptions[s["id"]] = s
    return ok(helpers.ser_subscription(s), 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription_ep(sid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    s = domain.get_subscription(sid)
    if role == "Customer" and not domain.owns_subscription(uid, s):
        deny_ownership()
    return ok(helpers.ser_subscription(s))


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    limit, offset = read_pagination()
    customer_id = request.args.get("customer_id")
    plan_id = request.args.get("plan_id")
    items = list(db.subscriptions.values())
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == uid]
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if plan_id is not None:
        items = [s for s in items if s["plan_id"] == plan_id]
    data, pagination = paginate(items, limit, offset, helpers.ser_subscription)
    return ok(data, 200, "array", pagination)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Customer"})
    s = domain.get_subscription(sid)
    if not domain.owns_subscription(uid, s):
        deny_ownership()
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE")
    # Cascade: open boxes -> cancelled (OPEN variant).
    for box in list(db.boxes.values()):
        if box["subscription_id"] == sid and box["fulfillment_status"] == "OPEN":
            domain.release_selected_items(box)
            box["fulfillment_status"] = "CANCELLED"
            box["billing_status"] = "WAIVED"
            box["refund_cents"] = 0
            box["refund_destination"] = "NONE"
            touch(box)
    # Cascade: scheduled pause windows -> cancelled.
    for pw in db.pause_windows.values():
        if pw["subscription_id"] == sid and pw["status"] == "SCHEDULED":
            pw["status"] = "CANCELLED"
            touch(pw)
    # Cascade: pending plan changes -> cancelled.
    for pc in db.plan_changes.values():
        if pc["subscription_id"] == sid and pc["status"] == "PENDING":
            pc["status"] = "CANCELLED"
            touch(pc)
    # Referral expiry: referee cancels before any first box shipped.
    if not domain.customer_first_box_shipped(s["customer_id"]):
        for r in db.referrals.values():
            if r["status"] == "PENDING" and r["referee_customer_id"] == s["customer_id"]:
                r["status"] = "EXPIRED"
                touch(r)
    s["status"] = "CANCELLED"
    touch(s)
    return ok(helpers.ser_subscription(s))


@app.route("/subscriptions/<sid>/pause-windows", methods=["POST"])
def create_pause(sid):
    uid, role = authenticate()
    authorize(role, {"Customer"})
    s = domain.get_subscription(sid)
    if not domain.owns_subscription(uid, s):
        deny_ownership()
    body = get_body()
    start_date = require_str(body, "start_date")
    end_date = require_str(body, "end_date")
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    if sd is None or ed is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "start_date/end_date must be YYYY-MM-DD")
    # Overlap check against SCHEDULED windows (adjacency allowed).
    for pw in db.pause_windows.values():
        if pw["subscription_id"] == sid and pw["status"] == "SCHEDULED":
            s2 = parse_date(pw["start_date"])
            e2 = parse_date(pw["end_date"])
            if sd < e2 and s2 < ed:
                raise ApiError("ERR_PAUSE_OVERLAP", 409, "Pause window overlaps an existing one")
    if ed <= sd:
        raise ApiError("ERR_INVALID_REQUEST", 422, "end_date must be after start_date")
    pw = base_fields()
    pw.update({"subscription_id": sid, "start_date": start_date, "end_date": end_date,
               "status": "SCHEDULED"})
    db.pause_windows[pw["id"]] = pw
    return ok(helpers.ser_pause(pw), 201)


@app.route("/subscriptions/<sid>/pause-windows", methods=["GET"])
def list_pauses(sid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    s = domain.get_subscription(sid)
    if role == "Customer" and not domain.owns_subscription(uid, s):
        deny_ownership()
    limit, offset = read_pagination()
    items = [pw for pw in db.pause_windows.values() if pw["subscription_id"] == sid]
    data, pagination = paginate(items, limit, offset, helpers.ser_pause)
    return ok(data, 200, "array", pagination)


@app.route("/subscriptions/<sid>/plan-changes", methods=["POST"])
def create_plan_change(sid):
    uid, role = authenticate()
    authorize(role, {"Customer"})
    s = domain.get_subscription(sid)
    if not domain.owns_subscription(uid, s):
        deny_ownership()
    body = get_body()
    to_plan_id = body.get("to_plan_id")
    if to_plan_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: to_plan_id")
    domain.get_plan(to_plan_id)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE")
    expected = body.get("expected_subscription_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError("ERR_INVALID_REQUEST", 422, "expected_subscription_version must be an integer")
        if expected != s["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "Subscription version is stale")
    effective_date = require_str(body, "effective_date")
    if parse_date(effective_date) is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "effective_date must be YYYY-MM-DD")
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: expected_subscription_version")
    # Supersede any prior PENDING plan change.
    for pc in db.plan_changes.values():
        if pc["subscription_id"] == sid and pc["status"] == "PENDING":
            pc["status"] = "SUPERSEDED"
            touch(pc)
    pc = base_fields()
    pc.update({
        "subscription_id": sid, "from_plan_id": s["plan_id"], "to_plan_id": to_plan_id,
        "effective_date": effective_date, "status": "PENDING",
    })
    db.plan_changes[pc["id"]] = pc
    touch(s)  # increments Subscription.version
    return ok(helpers.ser_plan_change(pc), 201)


@app.route("/plan-changes/<pcid>", methods=["GET"])
def get_plan_change_ep(pcid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    pc = domain.get_plan_change(pcid)
    if role == "Customer" and not domain.owns_plan_change(uid, pc):
        deny_ownership()
    return ok(helpers.ser_plan_change(pc))


@app.route("/plan-changes", methods=["GET"])
def list_plan_changes():
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    limit, offset = read_pagination()
    subscription_id = request.args.get("subscription_id")
    from_plan_id = request.args.get("from_plan_id")
    to_plan_id = request.args.get("to_plan_id")
    items = list(db.plan_changes.values())
    if role == "Customer":
        items = [pc for pc in items if domain.owns_plan_change(uid, pc)]
    if subscription_id is not None:
        items = [pc for pc in items if pc["subscription_id"] == subscription_id]
    if from_plan_id is not None:
        items = [pc for pc in items if pc["from_plan_id"] == from_plan_id]
    if to_plan_id is not None:
        items = [pc for pc in items if pc["to_plan_id"] == to_plan_id]
    data, pagination = paginate(items, limit, offset, helpers.ser_plan_change)
    return ok(data, 200, "array", pagination)


# ==========================================================================
# Box generation + selection
# ==========================================================================
def _valid_qty(raw):
    return isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1


@app.route("/subscriptions/<sid>/boxes", methods=["POST"])
def create_box(sid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    s = domain.get_subscription(sid)
    if role == "Customer" and not domain.owns_subscription(uid, s):
        deny_ownership()
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not ACTIVE")
    body = get_body()
    delivery_date = require_str(body, "delivery_date")
    if parse_date(delivery_date) is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "delivery_date must be YYYY-MM-DD")
    if any(b["subscription_id"] == sid and b["delivery_date"] == delivery_date
           for b in db.boxes.values()):
        raise ApiError("ERR_DUPLICATE", 422, "A box already exists for this delivery_date")
    # Apply any due PENDING plan change before snapshotting.
    dd = parse_date(delivery_date)
    for pc in db.plan_changes.values():
        if (pc["subscription_id"] == sid and pc["status"] == "PENDING"
                and parse_date(pc["effective_date"]) <= dd):
            new_plan = domain.get_plan(pc["to_plan_id"])
            pc["status"] = "APPLIED"
            touch(pc)
            s["plan_id"] = pc["to_plan_id"]
            s["meals_per_week"] = new_plan["meals_per_week"]
            touch(s)
            break
    plan = domain.get_plan(s["plan_id"])
    customer = domain.get_customer(s["customer_id"])
    zone = domain.get_zone(customer["shipping_zone_id"])
    is_first = not domain.customer_has_box(s["customer_id"])
    cold_snap = zone["cold_pack_fee_cents"] if zone["requires_cold_pack"] else 0
    b = base_fields()
    b.update({
        "subscription_id": sid, "delivery_date": delivery_date,
        "cutoff_at": compute_cutoff_at(delivery_date, zone),
        "plan_price_per_meal_cents": plan["price_per_meal_cents"],
        "meals_target": s["meals_per_week"],
        "base_shipping_fee_cents": zone["base_shipping_fee_cents"],
        "cold_pack_fee_snapshot_cents": cold_snap,
        "is_first_box": is_first,
        "fulfillment_status": "OPEN", "billing_status": "UNCHARGED",
        "subtotal_cents": 0, "discount_cents": 0, "shipping_fee_cents": 0,
        "cold_pack_fee_cents": 0, "credit_applied_cents": 0, "total_charged_cents": 0,
        "refund_cents": 0, "refund_destination": "NONE",
    })
    if date_in_pause(sid, delivery_date):
        b["fulfillment_status"] = "SKIPPED"
        b["billing_status"] = "WAIVED"
    db.boxes[b["id"]] = b
    return ok(helpers.ser_box(b), 201)


@app.route("/boxes/<bid>", methods=["GET"])
def get_box_ep(bid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    b = domain.get_box(bid)
    if role == "Customer" and not domain.owns_box(uid, b):
        deny_ownership()
    return ok(helpers.ser_box(b))


@app.route("/boxes", methods=["GET"])
def list_boxes():
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    limit, offset = read_pagination()
    subscription_id = request.args.get("subscription_id")
    items = list(db.boxes.values())
    if role == "Customer":
        items = [b for b in items if domain.owns_box(uid, b)]
    if subscription_id is not None:
        items = [b for b in items if b["subscription_id"] == subscription_id]
    data, pagination = paginate(items, limit, offset, helpers.ser_box)
    return ok(data, 200, "array", pagination)


@app.route("/boxes/<bid>/items", methods=["POST"])
def select_item(bid):
    uid, role = authenticate()
    authorize(role, {"Customer"})
    box = domain.get_box(bid)
    if not domain.owns_box(uid, box):
        deny_ownership()
    body = get_body()
    meal_id = body.get("meal_id")
    if meal_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: meal_id")
    meal = domain.get_meal(meal_id)
    qty_raw = body.get("quantity", 1)
    valid = _valid_qty(qty_raw)
    eff_qty = qty_raw if valid else 1
    if box["fulfillment_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Box is not OPEN")
    if now_clock() >= parse_iso(box["cutoff_at"]):
        raise ApiError("ERR_CUTOFF_PASSED", 409, "Selection window has closed")
    customer = domain.customer_of_box(box)
    if set(meal["allergens"]) & set(customer["allergen_exclusions"]):
        raise ApiError("ERR_ALLERGEN_CONFLICT", 422, "Meal conflicts with allergen exclusions")
    run = domain.find_available_run(meal_id, box["delivery_date"], eff_qty)
    if run is None:
        raise ApiError("ERR_MEAL_SOLD_OUT", 409, "No available run has enough servings")
    sub = db.subscriptions.get(box["subscription_id"])
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not ACTIVE")
    if not valid:
        raise ApiError("ERR_INVALID_REQUEST", 422, "quantity must be an integer >= 1")
    item = base_fields()
    item.update({
        "box_id": box["id"], "meal_id": meal_id, "quantity": eff_qty,
        "reserved_run_id": run["id"],
        "line_gross_cents": box["plan_price_per_meal_cents"] * eff_qty,
        "status": "SELECTED",
    })
    db.box_items[item["id"]] = item
    domain.reconcile_run(run)
    return ok(helpers.ser_box_item(item), 201)


@app.route("/box-items/<iid>", methods=["GET"])
def get_box_item_ep(iid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    item = domain.get_box_item(iid)
    if role == "Customer" and not domain.owns_box_item(uid, item):
        deny_ownership()
    return ok(helpers.ser_box_item(item))


@app.route("/box-items", methods=["GET"])
def list_box_items():
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    limit, offset = read_pagination()
    box_id = request.args.get("box_id")
    meal_id = request.args.get("meal_id")
    reserved_run_id = request.args.get("reserved_run_id")
    items = list(db.box_items.values())
    if role == "Customer":
        items = [i for i in items if domain.owns_box_item(uid, i)]
    if box_id is not None:
        items = [i for i in items if i["box_id"] == box_id]
    if meal_id is not None:
        items = [i for i in items if i["meal_id"] == meal_id]
    if reserved_run_id is not None:
        items = [i for i in items if i.get("reserved_run_id") == reserved_run_id]
    data, pagination = paginate(items, limit, offset, helpers.ser_box_item)
    return ok(data, 200, "array", pagination)


@app.route("/box-items/<iid>/swap", methods=["POST"])
def swap_item(iid):
    uid, role = authenticate()
    authorize(role, {"Customer"})
    item = domain.get_box_item(iid)
    if not domain.owns_box_item(uid, item):
        deny_ownership()
    body = get_body()
    new_meal_id = body.get("new_meal_id")
    if new_meal_id is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: new_meal_id")
    new_meal = domain.get_meal(new_meal_id)
    box = db.boxes.get(item["box_id"])
    if item["status"] != "SELECTED" or box["fulfillment_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Item or box is not in a swappable state")
    if now_clock() >= parse_iso(box["cutoff_at"]):
        raise ApiError("ERR_CUTOFF_PASSED", 409, "Selection window has closed")
    customer = domain.customer_of_box(box)
    if set(new_meal["allergens"]) & set(customer["allergen_exclusions"]):
        raise ApiError("ERR_ALLERGEN_CONFLICT", 422, "Meal conflicts with allergen exclusions")
    qty_raw = body.get("quantity", 1)
    valid = _valid_qty(qty_raw)
    eff_qty = qty_raw if valid else 1
    new_run = domain.find_available_run(new_meal_id, box["delivery_date"], eff_qty)
    if new_run is None:
        raise ApiError("ERR_MEAL_SOLD_OUT", 409, "No available run has enough servings")
    sub = db.subscriptions.get(box["subscription_id"])
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not ACTIVE")
    if not valid:
        raise ApiError("ERR_INVALID_REQUEST", 422, "quantity must be an integer >= 1")
    # Release the old line.
    old_run = db.runs.get(item.get("reserved_run_id"))
    item["status"] = "SWAPPED_OUT"
    item["reserved_run_id"] = None
    touch(item)
    if old_run is not None:
        domain.reconcile_run(old_run)
    # Reserve the new line.
    new_item = base_fields()
    new_item.update({
        "box_id": box["id"], "meal_id": new_meal_id, "quantity": eff_qty,
        "reserved_run_id": new_run["id"],
        "line_gross_cents": box["plan_price_per_meal_cents"] * eff_qty,
        "status": "SELECTED",
    })
    db.box_items[new_item["id"]] = new_item
    domain.reconcile_run(new_run)
    return ok(helpers.ser_box_item(new_item), 201)


@app.route("/boxes/<bid>/skip", methods=["POST"])
def skip_box(bid):
    uid, role = authenticate()
    authorize(role, {"Customer"})
    box = domain.get_box(bid)
    if not domain.owns_box(uid, box):
        deny_ownership()
    if box["fulfillment_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Box is not OPEN")
    if now_clock() >= parse_iso(box["cutoff_at"]):
        raise ApiError("ERR_CUTOFF_PASSED", 409, "Selection window has closed")
    domain.release_selected_items(box)
    box["fulfillment_status"] = "SKIPPED"
    box["billing_status"] = "WAIVED"
    touch(box)
    return ok(helpers.ser_box(box))


@app.route("/boxes/<bid>/lock", methods=["POST"])
def lock_box(bid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    box = domain.get_box(bid)
    if box["fulfillment_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Box is not OPEN")
    if now_clock() < parse_iso(box["cutoff_at"]):
        raise ApiError("ERR_INVALID_STATE", 409, "Cutoff has not been reached")
    sub = db.subscriptions.get(box["subscription_id"])
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription is not ACTIVE")
    if not domain.selected_items(box):
        raise ApiError("ERR_INVALID_STATE", 409, "Box has no SELECTED items")
    domain.compute_box_charge(box)
    box["fulfillment_status"] = "LOCKED"
    box["billing_status"] = "PENDING"
    touch(box)
    return ok(helpers.ser_box(box))


@app.route("/boxes/<bid>/ship", methods=["POST"])
def ship_box(bid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    box = domain.get_box(bid)
    if box["fulfillment_status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Box is not LOCKED")
    if box["billing_status"] == "CHARGE_FAILED":
        raise ApiError("ERR_PAYMENT_DECLINED", 402, "Box charge failed; cannot ship")
    if box["billing_status"] != "CHARGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Box has not been charged")
    box["fulfillment_status"] = "SHIPPED"
    touch(box)
    domain.fire_referral_reward(box)
    return ok(helpers.ser_box(box))


@app.route("/boxes/<bid>/deliver", methods=["POST"])
def deliver_box(bid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    box = domain.get_box(bid)
    if box["fulfillment_status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE", 409, "Box is not SHIPPED")
    box["fulfillment_status"] = "DELIVERED"
    touch(box)
    return ok(helpers.ser_box(box))


@app.route("/boxes/<bid>/cancel", methods=["POST"])
def cancel_box(bid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    box = domain.get_box(bid)
    if role == "Customer" and not domain.owns_box(uid, box):
        deny_ownership()
    ff = box["fulfillment_status"]
    if ff not in ("OPEN", "LOCKED", "SHIPPED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Box cannot be cancelled from its current state")
    if role == "Customer" and ff != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Customers may only cancel an OPEN box")
    customer = domain.customer_of_box(box)
    if ff == "LOCKED" and box["billing_status"] not in ("CHARGED", "PENDING", "CHARGE_FAILED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Box is not in a cancellable billing state")
    if ff == "SHIPPED" and box["billing_status"] != "CHARGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Box is not in a cancellable billing state")
    domain.release_selected_items(box)
    if ff == "OPEN":
        box["billing_status"] = "WAIVED"
        box["refund_cents"] = 0
        box["refund_destination"] = "NONE"
    elif ff == "LOCKED":
        box["refund_cents"] = box["total_charged_cents"]
        box["refund_destination"] = "ORIGINAL_PAYMENT"
        if box["billing_status"] == "CHARGED":
            box["billing_status"] = "REFUNDED"
            if box["credit_applied_cents"] > 0:
                domain.add_ledger(customer["id"], box["credit_applied_cents"],
                                  "REFUND_CREDIT", box_id=box["id"])
    else:  # SHIPPED
        refund = box["total_charged_cents"] - box["shipping_fee_cents"] - box["cold_pack_fee_cents"]
        if refund < 0:
            refund = 0
        box["refund_cents"] = refund
        box["refund_destination"] = "WALLET_CREDIT"
        if refund > 0:
            domain.add_ledger(customer["id"], refund, "REFUND_CREDIT", box_id=box["id"])
        box["billing_status"] = "REFUNDED"
    box["fulfillment_status"] = "CANCELLED"
    touch(box)
    return ok(helpers.ser_box(box))


# ==========================================================================
# Referral + credit ledger (read-only surfaces)
# ==========================================================================
@app.route("/referrals/<rid>", methods=["GET"])
def get_referral_ep(rid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    r = domain.get_referral(rid)
    if role == "Customer" and not domain.owns_referral(uid, r):
        deny_ownership()
    return ok(helpers.ser_referral(r))


@app.route("/referrals", methods=["GET"])
def list_referrals():
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    limit, offset = read_pagination()
    referrer = request.args.get("referrer_customer_id")
    referee = request.args.get("referee_customer_id")
    items = list(db.referrals.values())
    if role == "Customer":
        items = [r for r in items if domain.owns_referral(uid, r)]
    if referrer is not None:
        items = [r for r in items if r["referrer_customer_id"] == referrer]
    if referee is not None:
        items = [r for r in items if r["referee_customer_id"] == referee]
    data, pagination = paginate(items, limit, offset, helpers.ser_referral)
    return ok(data, 200, "array", pagination)


@app.route("/credit-ledger/<lid>", methods=["GET"])
def get_ledger_ep(lid):
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    e = domain.get_ledger(lid)
    if role == "Customer" and not domain.owns_ledger(uid, e):
        deny_ownership()
    return ok(helpers.ser_ledger(e))


@app.route("/credit-ledger", methods=["GET"])
def list_ledger():
    uid, role = authenticate()
    authorize(role, {"Customer", "PlatformAdmin"})
    limit, offset = read_pagination()
    customer_id = request.args.get("customer_id")
    box_id = request.args.get("box_id")
    items = list(db.ledger.values())
    if role == "Customer":
        items = [e for e in items if domain.owns_ledger(uid, e)]
    if customer_id is not None:
        items = [e for e in items if e["customer_id"] == customer_id]
    if box_id is not None:
        items = [e for e in items if e.get("box_id") == box_id]
    data, pagination = paginate(items, limit, offset, helpers.ser_ledger)
    return ok(data, 200, "array", pagination)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
