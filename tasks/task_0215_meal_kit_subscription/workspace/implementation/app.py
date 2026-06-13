"""Meal Kit Subscription API — Flask entry point.

In-memory storage only (db.py). The store starts empty on every boot and is
never seeded. All endpoints, fields, side effects, and errors trace to PRD.md.
"""
import os
import uuid as _uuid

from flask import Flask, request

import db
import errors
import response
import serializers as ser
import validate as v
import lookups as lk
import listing
import calculations as calc
import clock
import timeutil
from context import require_context, require_role

app = Flask(__name__)
app.url_map.strict_slashes = False


# ----------------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    # Unknown route — not an entity-existence error; surface as generic 404.
    return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return handle_api_error(e)
    return response.error_response("ERR_INTERNAL", str(e), 500)


# ----------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------
def _list_filtered(collection, filters):
    """Filter a collection dict by equality on the given field->value pairs."""
    items = []
    for e in collection.values():
        ok = True
        for field, val in filters.items():
            if val is None:
                continue
            if e.get(field) != val:
                ok = False
                break
        if ok:
            items.append(e)
    items.sort(key=listing.sort_key)
    return items


# ===========================================================================
# Plan (catalog)
# ===========================================================================
@app.route("/plans", methods=["POST"])
def create_plan():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin")
    body = v.get_json_body()
    code = v.require_str(body, "code")
    servings_per_meal = v.require_int(body, "servings_per_meal")
    v.in_set("servings_per_meal", servings_per_meal, (2, 4))
    meals_per_week = v.require_int(body, "meals_per_week")
    v.in_range("meals_per_week", meals_per_week, 2, 6)
    is_active = v.opt_bool(body, "is_active", True)

    now = clock.get_now()
    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["code"] = code
    e["servings_per_meal"] = servings_per_meal
    e["meals_per_week"] = meals_per_week
    e["is_active"] = is_active
    db.plans[e["id"]] = e
    return response.object_response(ser.plan(e), 201)


@app.route("/plans", methods=["GET"])
def list_plans():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    limit, offset = v.parse_pagination()
    is_active = _parse_bool_query("is_active")
    items = _list_filtered(db.plans, {"is_active": is_active})
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.plan(x) for x in page], limit, offset, total)


@app.route("/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    e = lk.get_plan(plan_id)
    return response.object_response(ser.plan(e))


# ===========================================================================
# ShippingZone (catalog)
# ===========================================================================
@app.route("/shipping-zones", methods=["POST"])
def create_zone():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin")
    body = v.get_json_body()
    zone_code = v.require_str(body, "zone_code")
    v.in_set("zone_code", zone_code, ("ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"))
    surcharge = v.require_int(body, "cold_pack_surcharge_cents")
    if surcharge < 0:
        raise errors.err(errors.ERR_VALIDATION, "cold_pack_surcharge_cents must be >= 0")
    cutoff_weekday = v.require_int(body, "cutoff_weekday")
    v.in_range("cutoff_weekday", cutoff_weekday, 1, 7)
    serviceable = v.opt_bool(body, "serviceable", True)

    now = clock.get_now()
    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["zone_code"] = zone_code
    e["cold_pack_surcharge_cents"] = surcharge
    e["cutoff_weekday"] = cutoff_weekday
    e["serviceable"] = serviceable
    db.shipping_zones[e["id"]] = e
    return response.object_response(ser.shipping_zone(e), 201)


@app.route("/shipping-zones", methods=["GET"])
def list_zones():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    limit, offset = v.parse_pagination()
    items = _list_filtered(db.shipping_zones, {})
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.shipping_zone(x) for x in page], limit, offset, total)


@app.route("/shipping-zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    e = lk.get_zone(zone_id)
    return response.object_response(ser.shipping_zone(e))


# ===========================================================================
# Recipe (catalog)
# ===========================================================================
@app.route("/recipes", methods=["POST"])
def create_recipe():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin")
    body = v.get_json_body()
    title = v.require_str(body, "title")
    is_premium = v.opt_bool(body, "is_premium", False)
    contains_allergens = v.opt_str_array(body, "contains_allergens", [])
    diet_tags = v.opt_str_array(body, "diet_tags", [])
    is_available = v.opt_bool(body, "is_available", True)

    now = clock.get_now()
    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["title"] = title
    e["is_premium"] = is_premium
    e["contains_allergens"] = contains_allergens
    e["diet_tags"] = diet_tags
    e["is_available"] = is_available
    db.recipes[e["id"]] = e
    return response.object_response(ser.recipe(e), 201)


@app.route("/recipes", methods=["GET"])
def list_recipes():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    limit, offset = v.parse_pagination()
    is_available = _parse_bool_query("is_available")
    items = _list_filtered(db.recipes, {"is_available": is_available})
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.recipe(x) for x in page], limit, offset, total)


@app.route("/recipes/<recipe_id>", methods=["GET"])
def get_recipe(recipe_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    e = lk.get_recipe(recipe_id)
    return response.object_response(ser.recipe(e))


@app.route("/recipes/<recipe_id>/box-recipes", methods=["GET"])
def list_recipe_box_recipes(recipe_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    lk.get_recipe(recipe_id)
    limit, offset = v.parse_pagination()
    items = _list_filtered(db.box_recipes, {"recipe_id": recipe_id})
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.box_recipe(x) for x in page], limit, offset, total)


# ===========================================================================
# Member
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    ctx = require_context()
    require_role(ctx, "Anonymous")
    body = v.get_json_body()
    email = v.require_str(body, "email")
    full_name = v.require_str(body, "full_name")
    shipping_zone_id = v.require_str(body, "shipping_zone_id")
    referred_by = v.opt_str(body, "referred_by_member_id", None)

    # Existence (priority 3): zone, then referrer if supplied.
    zone = lk.get_zone(shipping_zone_id)
    referrer = None
    if referred_by is not None:
        referrer = lk.get_member(referred_by)

    # Business referential (priority 12): zone must be serviceable.
    if not zone["serviceable"]:
        raise errors.err(errors.ERR_ZONE_NOT_SERVICEABLE)

    now = clock.get_now()
    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["email"] = email
    e["full_name"] = full_name
    e["shipping_zone_id"] = shipping_zone_id
    e["referred_by_member_id"] = referred_by
    e["referral_code"] = "REF-" + _uuid.uuid4().hex[:12].upper()
    e["credit_balance_cents"] = 0
    e["lifetime_box_count"] = 0
    e["status"] = "ACTIVE"
    db.members[e["id"]] = e

    # A supplied referred_by establishes a PENDING Referral linking referrer
    # to the new referee (PRD §3.2, §3.7).
    if referrer is not None:
        _create_referral_record(referrer["id"], e["id"], now)

    return response.object_response(ser.member(e), 201)


@app.route("/members", methods=["GET"])
def list_members():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin")
    limit, offset = v.parse_pagination()
    referred_by = request.args.get("referred_by_member_id")
    shipping_zone_id = request.args.get("shipping_zone_id")
    items = _list_filtered(db.members, {
        "referred_by_member_id": referred_by,
        "shipping_zone_id": shipping_zone_id,
    })
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.member(x) for x in page], limit, offset, total)


@app.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    e = lk.get_member(member_id)
    lk.assert_member_self(ctx, member_id)
    return response.object_response(ser.member(e))


@app.route("/members/<member_id>/referral-summary", methods=["GET"])
def referral_summary(member_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    lk.get_member(member_id)
    lk.assert_member_self(ctx, member_id)
    pending = [r for r in db.referrals.values()
               if r["referrer_member_id"] == member_id and r["status"] == "PENDING"]
    settled = [r for r in db.referrals.values()
               if r["referrer_member_id"] == member_id and r["status"] == "SETTLED"]
    pending_count = len(pending)
    forward_estimate_cents = calc.REFERRAL_REWARD_CENTS * pending_count
    settled_total_cents = sum(r["reward_cents"] for r in settled)
    data = {
        "forward_estimate_cents": forward_estimate_cents,
        "settled_total_cents": settled_total_cents,
        "pending_count": pending_count,
    }
    return response.object_response(data)


@app.route("/members/<member_id>/deactivate", methods=["POST"])
def deactivate_member(member_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin")
    m = lk.get_member(member_id)
    # State (priority 4): must be ACTIVE.
    if m["status"] != "ACTIVE":
        raise errors.err(errors.ERR_MEMBER_NOT_ACTIVE)
    # Cross-entity (PRD §3.2): no ACTIVE/PAUSED subscription.
    for s in db.subscriptions.values():
        if s["member_id"] == member_id and s["status"] in ("ACTIVE", "PAUSED"):
            raise errors.err(errors.ERR_MEMBER_HAS_LIVE_SUBSCRIPTION)

    now = clock.get_now()
    m["status"] = "DEACTIVATED"
    db.touch(m, now)
    # Cascade: VOID PENDING referrals where this member is referee; reward stays 0.
    for r in db.referrals.values():
        if r["referee_member_id"] == member_id and r["status"] == "PENDING":
            r["status"] = "VOID"
            r["reward_cents"] = 0
            db.touch(r, now)
    return response.object_response(ser.member(m))


# ===========================================================================
# Subscription
# ===========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    ctx = require_context()
    require_role(ctx, "Member")
    body = v.get_json_body()
    member_id = v.require_str(body, "member_id")
    plan_id = v.require_str(body, "plan_id")
    diet_preference = v.opt_str(body, "diet_preference", "STANDARD")
    v.in_set("diet_preference", diet_preference,
             ("STANDARD", "VEGETARIAN", "PESCATARIAN", "LOW_CARB", "FAMILY_FRIENDLY"))
    blocked_allergens = v.opt_str_array(body, "blocked_allergens", [])
    monthly_addon_fee_cents = v.opt_int(body, "monthly_addon_fee_cents", 0)
    if monthly_addon_fee_cents < 0:
        raise errors.err(errors.ERR_VALIDATION, "monthly_addon_fee_cents must be >= 0")
    billing_cycle_day = v.require_int(body, "billing_cycle_day")
    v.in_range("billing_cycle_day", billing_cycle_day, 1, 28)

    # Authorization (priority 2): a Member creates own subscription.
    if ctx.role == "Member" and member_id != ctx.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED)
    # Existence (priority 3): member, then plan.
    lk.get_member(member_id)
    plan = lk.get_plan(plan_id)
    # Business referential (priority 12): plan must be active.
    if not plan["is_active"]:
        raise errors.err(errors.ERR_PLAN_INACTIVE)

    now = clock.get_now()
    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["member_id"] = member_id
    e["plan_id"] = plan_id
    e["diet_preference"] = diet_preference
    e["blocked_allergens"] = blocked_allergens
    e["monthly_addon_fee_cents"] = monthly_addon_fee_cents
    e["billing_cycle_day"] = billing_cycle_day
    e["scheduled_resume_date"] = None
    e["status"] = "ACTIVE"
    # Internal: list of pause windows [start_iso, resume_iso] for overlap checks.
    e["_pause_windows"] = []
    db.subscriptions[e["id"]] = e
    return response.object_response(ser.subscription(e), 201)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    limit, offset = v.parse_pagination()
    member_id = request.args.get("member_id")
    plan_id = request.args.get("plan_id")
    items = _list_filtered(db.subscriptions, {"member_id": member_id, "plan_id": plan_id})
    if ctx.role == "Member":
        items = [s for s in items if s["member_id"] == ctx.user_id]
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.subscription(x) for x in page], limit, offset, total)


@app.route("/subscriptions/<sub_id>", methods=["GET"])
def get_subscription(sub_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    s = lk.get_subscription(sub_id)
    lk.assert_member_owns_subscription(ctx, s)
    return response.object_response(ser.subscription(s))


@app.route("/subscriptions/<sub_id>/plan-changes", methods=["POST"])
def change_plan(sub_id):
    ctx = require_context()
    require_role(ctx, "Member")
    body = v.get_json_body()
    plan_id = v.require_str(body, "plan_id")
    expected_version = v.require_int(body, "expected_subscription_version")

    s = lk.get_subscription(sub_id)
    lk.assert_member_owns_subscription(ctx, s)
    plan = lk.get_plan(plan_id)
    # OCC (priority 5): expected version must equal current version.
    if expected_version != s["version"]:
        raise errors.err(errors.ERR_STALE_SUBSCRIPTION_VERSION)
    # Business referential (priority 12): new plan must be active.
    if not plan["is_active"]:
        raise errors.err(errors.ERR_PLAN_INACTIVE)

    now = clock.get_now()
    s["plan_id"] = plan_id
    db.touch(s, now)
    return response.object_response(ser.subscription(s))


@app.route("/subscriptions/<sub_id>/pause", methods=["POST"])
def pause_subscription(sub_id):
    ctx = require_context()
    require_role(ctx, "Member")
    body = v.get_json_body()
    resume_date_raw = v.require(body, "resume_date")
    resume_dt = timeutil.parse_iso(resume_date_raw)
    if resume_dt is None:
        raise errors.err(errors.ERR_VALIDATION, "resume_date must be an ISO 8601 datetime")

    s = lk.get_subscription(sub_id)
    lk.assert_member_owns_subscription(ctx, s)
    # State (priority 4): must be ACTIVE.
    if s["status"] != "ACTIVE":
        raise errors.err(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)

    now = clock.get_now()
    # Temporal/business (PRD §3.3): resume_date strictly after current clock date.
    if timeutil.date_of(resume_dt) <= timeutil.date_of(now):
        raise errors.err(errors.ERR_INVALID_RESUME_DATE)

    # Pause-window overlap (priority 11): [now, resume_date) half-open intervals;
    # adjacency allowed.
    new_start = now
    new_end = resume_dt
    for w in s["_pause_windows"]:
        if w.get("cancelled"):
            continue
        w_start = timeutil.parse_iso(w["start"])
        w_end = timeutil.parse_iso(w["resume"])
        # Half-open overlap: max(starts) < min(ends).
        if max(new_start, w_start) < min(new_end, w_end):
            raise errors.err(errors.ERR_PAUSE_WINDOW_OVERLAP)

    # Apply pause.
    s["status"] = "PAUSED"
    s["scheduled_resume_date"] = timeutil.now_iso(resume_dt)
    s["_pause_windows"].append({
        "start": timeutil.now_iso(new_start),
        "resume": timeutil.now_iso(new_end),
        "cancelled": False,
    })
    # Pause proration credit -> Member.credit_balance_cents (ledger sync).
    credit = calc.pause_proration_credit(
        s["monthly_addon_fee_cents"], s["billing_cycle_day"], now)
    if credit != 0:
        member = db.members[s["member_id"]]
        member["credit_balance_cents"] += credit
        db.touch(member, now)
    # Cascade: in-window OPEN+PENDING boxes delivering on/before resume_date -> SKIPPED.
    for b in db.weekly_boxes.values():
        if (b["subscription_id"] == sub_id
                and b["selection_status"] == "OPEN"
                and b["fulfillment_status"] == "PENDING"):
            delivery_dt = timeutil.parse_iso(b["delivery_date"])
            if delivery_dt is not None and delivery_dt <= resume_dt:
                b["selection_status"] = "SKIPPED"
                db.touch(b, now)
    db.touch(s, now)
    return response.object_response(ser.subscription(s))


@app.route("/subscriptions/<sub_id>/resume", methods=["POST"])
def resume_subscription(sub_id):
    ctx = require_context()
    require_role(ctx, "Member")
    s = lk.get_subscription(sub_id)
    lk.assert_member_owns_subscription(ctx, s)
    # State (priority 4): must be PAUSED.
    if s["status"] != "PAUSED":
        raise errors.err(errors.ERR_SUBSCRIPTION_NOT_PAUSED)

    now = clock.get_now()
    s["status"] = "ACTIVE"
    s["scheduled_resume_date"] = None
    db.touch(s, now)
    return response.object_response(ser.subscription(s))


@app.route("/subscriptions/<sub_id>/cancel", methods=["POST"])
def cancel_subscription(sub_id):
    ctx = require_context()
    require_role(ctx, "Member")
    s = lk.get_subscription(sub_id)
    lk.assert_member_owns_subscription(ctx, s)
    # State (priority 4): ACTIVE or PAUSED; terminal CANCELLED is rejected.
    if s["status"] == "ACTIVE":
        pass
    elif s["status"] == "PAUSED":
        pass
    else:
        # CANCELLED. Cancelling from ACTIVE requires ACTIVE; report that error.
        raise errors.err(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)

    now = clock.get_now()
    from_paused = s["status"] == "PAUSED"
    s["status"] = "CANCELLED"
    if from_paused:
        s["scheduled_resume_date"] = None
        # Mark live pause windows cancelled so they no longer block future logic.
        for w in s["_pause_windows"]:
            w["cancelled"] = True
    # Cascade: PENDING boxes -> selection SKIPPED, fulfillment stays PENDING.
    for b in db.weekly_boxes.values():
        if b["subscription_id"] == sub_id and b["fulfillment_status"] == "PENDING":
            if b["selection_status"] != "SKIPPED":
                b["selection_status"] = "SKIPPED"
                db.touch(b, now)
    db.touch(s, now)
    return response.object_response(ser.subscription(s))


# ===========================================================================
# WeeklyBox
# ===========================================================================
@app.route("/weekly-boxes", methods=["POST"])
def create_weekly_box():
    ctx = require_context()
    require_role(ctx, "Member")
    body = v.get_json_body()
    subscription_id = v.require_str(body, "subscription_id")
    delivery_raw = v.require(body, "delivery_date")
    delivery_dt = timeutil.parse_iso(delivery_raw)
    if delivery_dt is None:
        raise errors.err(errors.ERR_VALIDATION, "delivery_date must be an ISO 8601 datetime")

    s = lk.get_subscription(subscription_id)
    lk.assert_member_owns_subscription(ctx, s)

    now = clock.get_now()
    # delivery_date strictly after current clock date (SCAFFOLD field constraint).
    if timeutil.date_of(delivery_dt) <= timeutil.date_of(now):
        raise errors.err(errors.ERR_VALIDATION,
                         "delivery_date must be strictly after the current clock date")
    # Overlap (priority 10): at most one non-SKIPPED box per delivery_date.
    new_date = timeutil.date_of(delivery_dt)
    for b in db.weekly_boxes.values():
        if (b["subscription_id"] == subscription_id
                and b["selection_status"] != "SKIPPED"
                and timeutil.date_of(timeutil.parse_iso(b["delivery_date"])) == new_date):
            raise errors.err(errors.ERR_DELIVERY_DATE_TAKEN)

    # cutoff_at from delivery_date + member's shipping zone cutoff_weekday.
    member = db.members[s["member_id"]]
    zone = db.shipping_zones[member["shipping_zone_id"]]
    cutoff_dt = calc.cutoff_at(delivery_dt, zone["cutoff_weekday"])

    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["subscription_id"] = subscription_id
    e["delivery_date"] = timeutil.now_iso(delivery_dt)
    e["cutoff_at"] = timeutil.now_iso(cutoff_dt)
    e["provisional_charge_cents"] = 0
    e["final_charge_cents"] = None
    e["selection_status"] = "OPEN"
    e["fulfillment_status"] = "PENDING"
    db.weekly_boxes[e["id"]] = e
    return response.object_response(ser.weekly_box(e), 201)


@app.route("/weekly-boxes", methods=["GET"])
def list_weekly_boxes():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    limit, offset = v.parse_pagination()
    subscription_id = request.args.get("subscription_id")
    items = _list_filtered(db.weekly_boxes, {"subscription_id": subscription_id})
    if ctx.role == "Member":
        items = [b for b in items if lk.member_of_box(b) == ctx.user_id]
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.weekly_box(x) for x in page], limit, offset, total)


@app.route("/weekly-boxes/<box_id>", methods=["GET"])
def get_weekly_box(box_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    b = lk.get_weekly_box(box_id)
    lk.assert_member_owns_box(ctx, b)
    return response.object_response(ser.weekly_box(b))


@app.route("/weekly-boxes/<box_id>/recipes", methods=["POST"])
def add_box_recipe(box_id):
    ctx = require_context()
    require_role(ctx, "Member")
    body = v.get_json_body()
    recipe_id = v.require_str(body, "recipe_id")

    b = lk.get_weekly_box(box_id)
    lk.assert_member_owns_box(ctx, b)
    recipe = lk.get_recipe(recipe_id)
    sub = db.subscriptions[b["subscription_id"]]

    # State (priority 4): box selection must be OPEN.
    if b["selection_status"] != "OPEN":
        raise errors.err(errors.ERR_SELECTION_NOT_OPEN)
    # Temporal (priority 6): before cutoff.
    now = clock.get_now()
    cutoff = timeutil.parse_iso(b["cutoff_at"])
    if now >= cutoff:
        raise errors.err(errors.ERR_CUTOFF_PASSED)
    # Allergen safety (priority 7).
    blocked = set(sub["blocked_allergens"])
    if blocked & set(recipe["contains_allergens"]):
        raise errors.err(errors.ERR_ALLERGEN_BLOCKED)
    # Diet compatibility (priority 8).
    diet = sub["diet_preference"]
    if diet not in ("STANDARD", "FAMILY_FRIENDLY"):
        if diet not in recipe["diet_tags"]:
            raise errors.err(errors.ERR_DIET_INCOMPATIBLE)
    # Capacity + uniqueness (priority 9).
    plan = db.plans[sub["plan_id"]]
    existing = [br for br in db.box_recipes.values() if br["box_id"] == box_id]
    if any(br["recipe_id"] == recipe_id for br in existing):
        raise errors.err(errors.ERR_DUPLICATE_RECIPE)
    if len(existing) >= plan["meals_per_week"]:
        raise errors.err(errors.ERR_BOX_FULL)

    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["box_id"] = box_id
    e["recipe_id"] = recipe_id
    e["is_premium_snapshot"] = recipe["is_premium"]
    db.box_recipes[e["id"]] = e
    return response.object_response(ser.box_recipe(e), 201)


@app.route("/weekly-boxes/<box_id>/recipes", methods=["GET"])
def list_box_recipes(box_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    b = lk.get_weekly_box(box_id)
    lk.assert_member_owns_box(ctx, b)
    limit, offset = v.parse_pagination()
    items = _list_filtered(db.box_recipes, {"box_id": box_id})
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.box_recipe(x) for x in page], limit, offset, total)


@app.route("/weekly-boxes/<box_id>/recipes/<box_recipe_id>", methods=["DELETE"])
def delete_box_recipe(box_id, box_recipe_id):
    ctx = require_context()
    require_role(ctx, "Member")
    b = lk.get_weekly_box(box_id)
    lk.assert_member_owns_box(ctx, b)
    br = lk.get_box_recipe(box_recipe_id, box_id)
    # State (priority 4): box must be OPEN to remove a slot.
    if b["selection_status"] != "OPEN":
        raise errors.err(errors.ERR_SELECTION_NOT_OPEN)
    del db.box_recipes[br["id"]]
    return response.empty_response(204)


@app.route("/weekly-boxes/<box_id>/lock-selection", methods=["POST"])
def lock_selection(box_id):
    ctx = require_context()
    require_role(ctx, "Member")
    b = lk.get_weekly_box(box_id)
    lk.assert_member_owns_box(ctx, b)
    sub = db.subscriptions[b["subscription_id"]]

    # State (priority 4): selection OPEN.
    if b["selection_status"] != "OPEN":
        raise errors.err(errors.ERR_SELECTION_NOT_OPEN)
    # Cross-entity state: owning subscription ACTIVE.
    if sub["status"] != "ACTIVE":
        raise errors.err(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)
    # Selection complete: exactly plan.meals_per_week recipes.
    plan = db.plans[sub["plan_id"]]
    slot_count = sum(1 for br in db.box_recipes.values() if br["box_id"] == box_id)
    if slot_count != plan["meals_per_week"]:
        raise errors.err(errors.ERR_SELECTION_INCOMPLETE)
    # Temporal (priority 6): before cutoff.
    now = clock.get_now()
    cutoff = timeutil.parse_iso(b["cutoff_at"])
    if now >= cutoff:
        raise errors.err(errors.ERR_CUTOFF_PASSED)

    # Lock.
    b["selection_status"] = "LOCKED"
    member = db.members[sub["member_id"]]
    zone = db.shipping_zones[member["shipping_zone_id"]]
    premium_count = sum(1 for br in db.box_recipes.values()
                        if br["box_id"] == box_id and br["is_premium_snapshot"])
    charge, _credit = calc.weekly_box_charge(
        plan, sub, zone, premium_count,
        member["credit_balance_cents"], member["lifetime_box_count"])
    b["provisional_charge_cents"] = charge
    db.touch(b, now)
    return response.object_response(ser.weekly_box(b))


@app.route("/weekly-boxes/<box_id>/skip", methods=["POST"])
def skip_box(box_id):
    ctx = require_context()
    require_role(ctx, "Member")
    b = lk.get_weekly_box(box_id)
    lk.assert_member_owns_box(ctx, b)

    sel = b["selection_status"]
    now = clock.get_now()
    cutoff = timeutil.parse_iso(b["cutoff_at"])

    if sel == "OPEN":
        # Temporal (priority 6): before cutoff.
        if now >= cutoff:
            raise errors.err(errors.ERR_CUTOFF_PASSED)
        b["selection_status"] = "SKIPPED"
        db.touch(b, now)
    elif sel == "LOCKED":
        # Cross-dimension: fulfillment must be PENDING.
        if b["fulfillment_status"] != "PENDING":
            raise errors.err(errors.ERR_BOX_ALREADY_CHARGED)
        # Temporal (priority 6): before cutoff.
        if now >= cutoff:
            raise errors.err(errors.ERR_CUTOFF_PASSED)
        b["selection_status"] = "SKIPPED"
        b["provisional_charge_cents"] = 0
        db.touch(b, now)
    else:
        # SKIPPED already: skip requires OPEN (else ERR_SELECTION_NOT_OPEN).
        raise errors.err(errors.ERR_SELECTION_NOT_OPEN)
    return response.object_response(ser.weekly_box(b))


@app.route("/weekly-boxes/<box_id>/charge", methods=["POST"])
def charge_box(box_id):
    ctx = require_context()
    require_role(ctx, "PlatformOps")
    b = lk.get_weekly_box(box_id)
    sub = db.subscriptions[b["subscription_id"]]

    # State (priority 4): selection LOCKED.
    if b["selection_status"] != "LOCKED":
        raise errors.err(errors.ERR_BOX_NOT_LOCKED)
    # Fulfillment must be PENDING.
    if b["fulfillment_status"] != "PENDING":
        raise errors.err(errors.ERR_BOX_NOT_PENDING)
    # Temporal (priority 6): clock at/after cutoff.
    now = clock.get_now()
    cutoff = timeutil.parse_iso(b["cutoff_at"])
    if now < cutoff:
        raise errors.err(errors.ERR_CUTOFF_NOT_REACHED)

    plan = db.plans[sub["plan_id"]]
    member = db.members[sub["member_id"]]
    zone = db.shipping_zones[member["shipping_zone_id"]]
    premium_count = sum(1 for br in db.box_recipes.values()
                        if br["box_id"] == box_id and br["is_premium_snapshot"])
    charge, credit_applied = calc.weekly_box_charge(
        plan, sub, zone, premium_count,
        member["credit_balance_cents"], member["lifetime_box_count"])
    b["final_charge_cents"] = charge
    b["fulfillment_status"] = "CHARGED"
    b["_credit_applied"] = credit_applied
    if credit_applied != 0:
        member["credit_balance_cents"] -= credit_applied
        db.touch(member, now)
    db.touch(b, now)
    return response.object_response(ser.weekly_box(b))


@app.route("/weekly-boxes/<box_id>/ship", methods=["POST"])
def ship_box(box_id):
    ctx = require_context()
    require_role(ctx, "PlatformOps")
    b = lk.get_weekly_box(box_id)
    sub = db.subscriptions[b["subscription_id"]]
    member = db.members[sub["member_id"]]

    # State (priority 4): fulfillment CHARGED.
    if b["fulfillment_status"] != "CHARGED":
        raise errors.err(errors.ERR_BOX_NOT_CHARGED)
    # Cross-entity: owning member's zone serviceable.
    zone = db.shipping_zones[member["shipping_zone_id"]]
    if not zone["serviceable"]:
        raise errors.err(errors.ERR_ZONE_NOT_SERVICEABLE)

    now = clock.get_now()
    # Determine "first SHIPPED box" BEFORE bumping count.
    is_first_ship = not any(
        ob["fulfillment_status"] == "SHIPPED"
        and db.subscriptions[ob["subscription_id"]]["member_id"] == member["id"]
        for ob in db.weekly_boxes.values()
    )
    b["fulfillment_status"] = "SHIPPED"
    member["lifetime_box_count"] += 1
    db.touch(member, now)
    db.touch(b, now)

    # Cascade: referee's first SHIPPED box settles the referee's PENDING referral.
    if is_first_ship:
        _settle_referee_referral(member["id"], now)
    return response.object_response(ser.weekly_box(b))


@app.route("/weekly-boxes/<box_id>/refund", methods=["POST"])
def refund_box(box_id):
    ctx = require_context()
    require_role(ctx, "PlatformOps")
    b = lk.get_weekly_box(box_id)
    sub = db.subscriptions[b["subscription_id"]]
    member = db.members[sub["member_id"]]

    # State (priority 4): fulfillment CHARGED.
    if b["fulfillment_status"] != "CHARGED":
        raise errors.err(errors.ERR_BOX_NOT_CHARGED)

    now = clock.get_now()
    b["fulfillment_status"] = "REFUNDED"
    credit_applied = b.get("_credit_applied", 0)
    if credit_applied != 0:
        member["credit_balance_cents"] += credit_applied
        db.touch(member, now)
    db.touch(b, now)
    return response.object_response(ser.weekly_box(b))


# ===========================================================================
# Referral
# ===========================================================================
def _create_referral_record(referrer_id, referee_id, now):
    e = db.stamp_create(now)
    e["id"] = db.new_id()
    e["referrer_member_id"] = referrer_id
    e["referee_member_id"] = referee_id
    e["reward_cents"] = 0
    e["status"] = "PENDING"
    e["_settled_at"] = None
    db.referrals[e["id"]] = e
    return e


def _settle_referee_referral(referee_id, now):
    """Settle the referee's PENDING referral on its first SHIPPED box (PRD §3.7).

    Cap: if the referrer already has MAX_REFERRAL_REWARDS_PER_CYCLE settled
    referrals in the current billing cycle, this referral VOIDs with 0 reward.
    """
    ref = None
    for r in db.referrals.values():
        if r["referee_member_id"] == referee_id and r["status"] == "PENDING":
            ref = r
            break
    if ref is None:
        return
    referrer_id = ref["referrer_member_id"]
    settled_in_cycle = _settled_count_in_cycle(referrer_id, now)
    if settled_in_cycle < calc.MAX_REFERRAL_REWARDS_PER_CYCLE:
        ref["reward_cents"] = calc.REFERRAL_REWARD_CENTS
        ref["status"] = "SETTLED"
        ref["_settled_at"] = timeutil.now_iso(now)
        db.touch(ref, now)
        referrer = db.members.get(referrer_id)
        if referrer is not None:
            referrer["credit_balance_cents"] += calc.REFERRAL_REWARD_CENTS
            db.touch(referrer, now)
    else:
        ref["status"] = "VOID"
        ref["reward_cents"] = 0
        db.touch(ref, now)


def _settled_count_in_cycle(referrer_id, now):
    """Count the referrer's SETTLED referrals settled in the current billing cycle.

    The cycle is the 30-day window anchored at the referrer's most-recent
    billing_cycle_day (taken from their most-recently-created subscription). If
    the referrer has no subscription, all SETTLED referrals are counted.
    See module-level note on this resolved ambiguity.
    """
    anchor = _referrer_cycle_anchor(referrer_id, now)
    count = 0
    for r in db.referrals.values():
        if r["referrer_member_id"] != referrer_id or r["status"] != "SETTLED":
            continue
        if anchor is None:
            count += 1
            continue
        settled_at = timeutil.parse_iso(r.get("_settled_at")) if r.get("_settled_at") else None
        if settled_at is not None and settled_at >= anchor:
            count += 1
    return count


def _referrer_cycle_anchor(referrer_id, now):
    """Most-recent billing-cycle anchor datetime for the referrer, or None."""
    subs = [s for s in db.subscriptions.values() if s["member_id"] == referrer_id]
    if not subs:
        return None
    subs.sort(key=listing.sort_key)
    billing_cycle_day = subs[-1]["billing_cycle_day"]
    cur_date = timeutil.date_of(now)
    anchor_date = calc._most_recent_anchor(cur_date, billing_cycle_day)
    from datetime import datetime, timezone
    return datetime(anchor_date.year, anchor_date.month, anchor_date.day,
                    tzinfo=timezone.utc)


@app.route("/referrals", methods=["POST"])
def create_referral():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    body = v.get_json_body()
    referrer_id = v.require_str(body, "referrer_member_id")
    referee_id = v.require_str(body, "referee_member_id")

    # Authorization (priority 2): a Member may create only as the referrer.
    if ctx.role == "Member" and referrer_id != ctx.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED)
    # Existence (priority 3): referrer then referee.
    lk.get_member(referrer_id)
    lk.get_member(referee_id)
    # Business constraint (priority 13): no self-referral; referee not already referred.
    if referrer_id == referee_id:
        raise errors.err(errors.ERR_SELF_REFERRAL)
    for r in db.referrals.values():
        if r["referee_member_id"] == referee_id:
            raise errors.err(errors.ERR_REFEREE_ALREADY_REFERRED)

    now = clock.get_now()
    e = _create_referral_record(referrer_id, referee_id, now)
    return response.object_response(ser.referral(e), 201)


@app.route("/referrals", methods=["GET"])
def list_referrals():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    limit, offset = v.parse_pagination()
    referrer_id = request.args.get("referrer_member_id")
    referee_id = request.args.get("referee_member_id")
    items = _list_filtered(db.referrals, {
        "referrer_member_id": referrer_id,
        "referee_member_id": referee_id,
    })
    if ctx.role == "Member":
        items = [r for r in items
                 if r["referrer_member_id"] == ctx.user_id
                 or r["referee_member_id"] == ctx.user_id]
    page, total = listing.paginate(items, limit, offset)
    return response.array_response([ser.referral(x) for x in page], limit, offset, total)


@app.route("/referrals/<ref_id>", methods=["GET"])
def get_referral(ref_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin", "Member")
    r = lk.get_referral(ref_id)
    if ctx.role == "Member" and r["referrer_member_id"] != ctx.user_id \
            and r["referee_member_id"] != ctx.user_id:
        raise errors.err(errors.ERR_UNAUTHORIZED)
    return response.object_response(ser.referral(r))


@app.route("/referrals/<ref_id>/void", methods=["POST"])
def void_referral(ref_id):
    ctx = require_context()
    require_role(ctx, "PlatformAdmin")
    r = lk.get_referral(ref_id)
    # State (priority 4): must be PENDING.
    if r["status"] != "PENDING":
        raise errors.err(errors.ERR_REFERRAL_NOT_PENDING)
    now = clock.get_now()
    r["status"] = "VOID"
    r["reward_cents"] = 0
    db.touch(r, now)
    return response.object_response(ser.referral(r))


# ===========================================================================
# Test-driving clock
# ===========================================================================
@app.route("/_clock/set", methods=["POST"])
def set_clock():
    ctx = require_context()
    require_role(ctx, "PlatformAdmin")
    body = v.get_json_body()
    now_raw = v.require(body, "now_iso8601")
    dt = timeutil.parse_iso(now_raw)
    if dt is None:
        raise errors.err(errors.ERR_VALIDATION, "now_iso8601 must be an ISO 8601 datetime")
    clock.set_now(dt)
    return response.object_response({"now_iso8601": timeutil.now_iso(dt)})


# ----------------------------------------------------------------------------
# Query-param boolean parsing (filters like is_active / is_available)
# ----------------------------------------------------------------------------
def _parse_bool_query(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise errors.err(errors.ERR_VALIDATION, "%s must be a boolean" % name)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
