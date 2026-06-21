"""Catalogue routes: plans, price-schedules, add-ons, coupons, tax-jurisdictions
(PRD §3.1)."""
from flask import Blueprint

import errors
import serializers as S
import validate as V
from db import db, stamp_new, touch
from middleware import authenticate, require_role
from response import success
from util import parse_dt, parse_pagination, paginate, sort_by_created

bp = Blueprint("catalogue", __name__)


# =============================================================================
# Plans
# =============================================================================
@bp.route("/plans", methods=["POST"])
def create_plan():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    body = V.get_body()

    tier = V.require_enum(body, "tier", {"BASIC", "PRO", "ENTERPRISE"})
    monthly_fee = V.require_int(body, "monthly_fee_cents", minimum=0)
    included = V.require_int(body, "included_usage_units", minimum=0)
    overage_tiers = _validate_overage_tiers(body)
    trial_days = V.optional_int(body, "trial_days", minimum=0, default=0)

    # Unique tier among non-archived plans (priority 6 -> ERR_DUPLICATE).
    for p in db.plans.values():
        if p["tier"] == tier and p["status"] != "ARCHIVED":
            raise errors.duplicate(f"A non-archived plan with tier {tier} already exists")

    plan = {
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "included_usage_units": included,
        "overage_tiers": overage_tiers,
        "trial_days": trial_days,
        "status": "ACTIVE",
    }
    stamp_new(plan)
    db.plans[plan["id"]] = plan
    return success(S.ser_plan(plan), status=201)


def _validate_overage_tiers(body):
    tiers = V.require(body, "overage_tiers")
    if not isinstance(tiers, list):
        raise errors.invalid_request("overage_tiers must be an array")
    cleaned = []
    prev_cap = None
    for i, band in enumerate(tiers):
        if not isinstance(band, dict):
            raise errors.invalid_request("each overage tier must be an object")
        if "rate_cents_per_unit" not in band:
            raise errors.invalid_request("overage tier missing rate_cents_per_unit")
        rate = band["rate_cents_per_unit"]
        if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
            raise errors.invalid_request("rate_cents_per_unit must be a non-negative integer")
        up_to = band.get("up_to_units", None)
        is_last = (i == len(tiers) - 1)
        if up_to is None:
            if not is_last:
                raise errors.invalid_request("only the final overage tier may have up_to_units null")
        else:
            if isinstance(up_to, bool) or not isinstance(up_to, int) or up_to <= 0:
                raise errors.invalid_request("up_to_units must be a positive integer or null")
            if prev_cap is not None and up_to <= prev_cap:
                raise errors.invalid_request("overage tier up_to_units must strictly increase")
            prev_cap = up_to
        cleaned.append({"up_to_units": up_to, "rate_cents_per_unit": rate})
    return cleaned


@bp.route("/plans", methods=["GET"])
def list_plans():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    from flask import request
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = [p for p in db.plans.values() if status is None or p["status"] == status]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_plan(p) for p in page], is_array=True, pagination=pg)


@bp.route("/plans/<id>", methods=["GET"])
def get_plan(id):
    role, _ = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    plan = db.plans.get(id)
    if plan is None:
        raise errors.not_found("Plan not found")
    return success(S.ser_plan(plan))


@bp.route("/plans/<id>/archive", methods=["POST"])
def archive_plan(id):
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    plan = db.plans.get(id)
    if plan is None:
        raise errors.not_found("Plan not found")
    if plan["status"] == "ARCHIVED":
        raise errors.invalid_state("Plan is already archived")
    plan["status"] = "ARCHIVED"
    touch(plan)
    return success(S.ser_plan(plan))


# =============================================================================
# Plan price schedules (PRD §3.1)
# =============================================================================
@bp.route("/plans/<id>/price-schedules", methods=["POST"])
def create_price_schedule(id):
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    plan = db.plans.get(id)
    if plan is None:
        raise errors.not_found("Plan not found")
    body = V.get_body()

    monthly_fee = V.require_int(body, "monthly_fee_cents", minimum=0)
    eff_from_raw = V.require_str(body, "effective_from")
    eff_to_raw = V.require_str(body, "effective_to")
    eff_from = parse_dt(eff_from_raw)
    eff_to = parse_dt(eff_to_raw)
    if not (eff_from < eff_to):
        raise errors.invalid_request("effective_from must be strictly earlier than effective_to")

    # Half-open non-overlap against non-canceled schedules on this plan (priority 15).
    for s in db.price_schedules.values():
        if s["plan_id"] != id:
            continue
        # PlanPriceSchedule has no cancel transition; all existing are active.
        if eff_from < s["effective_to"] and s["effective_from"] < eff_to:
            raise errors.ApiError(errors.ERR_PRICE_SCHEDULE_OVERLAP, 409,
                                  "Price schedule overlaps an existing window")

    sched = {
        "plan_id": id,
        "monthly_fee_cents": monthly_fee,
        "effective_from": eff_from,
        "effective_to": eff_to,
    }
    stamp_new(sched)
    db.price_schedules[sched["id"]] = sched
    return success(S.ser_price_schedule(sched), status=201)


@bp.route("/plans/<id>/price-schedules", methods=["GET"])
def list_price_schedules(id):
    role, _ = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    plan = db.plans.get(id)
    if plan is None:
        raise errors.not_found("Plan not found")
    limit, offset = parse_pagination()
    items = [s for s in db.price_schedules.values() if s["plan_id"] == id]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_price_schedule(s) for s in page], is_array=True, pagination=pg)


# =============================================================================
# Add-ons (PRD §3.1)
# =============================================================================
@bp.route("/add-ons", methods=["POST"])
def create_addon():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    body = V.get_body()
    code = V.require_str(body, "code")
    monthly_fee = V.require_int(body, "monthly_fee_cents", minimum=0)
    for a in db.addons.values():
        if a["code"] == code:
            raise errors.duplicate(f"Add-on code {code} already exists")
    addon = {"code": code, "monthly_fee_cents": monthly_fee}
    stamp_new(addon)
    db.addons[addon["id"]] = addon
    return success(S.ser_addon(addon), status=201)


@bp.route("/add-ons", methods=["GET"])
def list_addons():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.addons.values()))
    page, pg = paginate(items, limit, offset)
    return success([S.ser_addon(a) for a in page], is_array=True, pagination=pg)


# =============================================================================
# Coupons (PRD §3.1)
# =============================================================================
@bp.route("/coupons", methods=["POST"])
def create_coupon():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    body = V.get_body()

    code = V.require_str(body, "code")
    discount_type = V.require_enum(body, "discount_type", {"PERCENT", "FIXED"})
    duration = V.require_enum(body, "duration", {"ONCE", "RECURRING"})
    max_redemptions = V.require_int(body, "max_redemptions", minimum=1)

    percent_off = None
    amount_off = None
    if discount_type == "PERCENT":
        if body.get("amount_off_cents") is not None:
            raise errors.invalid_request("amount_off_cents forbidden for PERCENT coupon")
        percent_off = V.require_int(body, "percent_off", minimum=1, maximum=100)
    else:  # FIXED
        if body.get("percent_off") is not None:
            raise errors.invalid_request("percent_off forbidden for FIXED coupon")
        amount_off = V.require_int(body, "amount_off_cents", minimum=1)

    # Unique code among non-expired coupons. No expiry transition exists, so all
    # stored coupons are non-expired -> unique across all.
    for c in db.coupons.values():
        if c["code"] == code:
            raise errors.duplicate(f"Coupon code {code} already exists")

    coupon = {
        "code": code,
        "discount_type": discount_type,
        "percent_off": percent_off,
        "amount_off_cents": amount_off,
        "duration": duration,
        "max_redemptions": max_redemptions,
        "redemption_count": 0,
        "status": "ACTIVE",
    }
    stamp_new(coupon)
    db.coupons[coupon["id"]] = coupon
    return success(S.ser_coupon(coupon), status=201)


@bp.route("/coupons", methods=["GET"])
def list_coupons():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    from flask import request
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = [c for c in db.coupons.values() if status is None or c["status"] == status]
    items = sort_by_created(items)
    page, pg = paginate(items, limit, offset)
    return success([S.ser_coupon(c) for c in page], is_array=True, pagination=pg)


@bp.route("/coupons/<id>", methods=["GET"])
def get_coupon(id):
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    coupon = db.coupons.get(id)
    if coupon is None:
        raise errors.not_found("Coupon not found")
    return success(S.ser_coupon(coupon))


# =============================================================================
# Tax jurisdictions (PRD §3.1)
# =============================================================================
@bp.route("/tax-jurisdictions", methods=["POST"])
def create_jurisdiction():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    body = V.get_body()
    region_code = V.require_str(body, "region_code")
    tax_rate_bps = V.require_int(body, "tax_rate_bps", minimum=0, maximum=10000)
    for j in db.tax_jurisdictions.values():
        if j["region_code"] == region_code:
            raise errors.duplicate(f"Jurisdiction {region_code} already exists")
    jur = {"region_code": region_code, "tax_rate_bps": tax_rate_bps}
    stamp_new(jur)
    db.tax_jurisdictions[jur["id"]] = jur
    return success(S.ser_jurisdiction(jur), status=201)


@bp.route("/tax-jurisdictions", methods=["GET"])
def list_jurisdictions():
    role, _ = authenticate()
    require_role(role, {"BillingAdmin"})
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.tax_jurisdictions.values()))
    page, pg = paginate(items, limit, offset)
    return success([S.ser_jurisdiction(j) for j in page], is_array=True, pagination=pg)
