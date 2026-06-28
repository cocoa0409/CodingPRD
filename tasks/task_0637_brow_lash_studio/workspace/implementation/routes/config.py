"""Studio, ServiceType, MembershipPlan routes (PRD §3.1)."""
from flask import Blueprint

import errors
from common import (bad_request, get_json_body, parse_pagination, paginate,
                    require_int, require_number, require_str, sort_by_created,
                    stamp_create, touch)
from db import store
from lookups import get_service_type_or_404, get_studio_or_404
from middleware import get_user_context, require_role
from response import success_list, success_object
import serialize

bp = Blueprint("config", __name__)

READ_ROLES = {"StudioManager", "FrontDesk", "LashTech", "Member"}


# ----------------------------- Studio --------------------------------------
@bp.route("/studios", methods=["POST"])
def create_studio():
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    body = get_json_body()
    name = require_str(body, "name")

    deposit_rate_pct = body.get("deposit_rate_pct", 0.20)
    if not isinstance(deposit_rate_pct, (int, float)) or isinstance(deposit_rate_pct, bool):
        raise bad_request("deposit_rate_pct must be a number.")
    if not (0 <= deposit_rate_pct <= 1):
        raise bad_request("deposit_rate_pct must be within [0, 1].")

    late_cancel_cutoff_hours = body.get("late_cancel_cutoff_hours", 24)
    if not isinstance(late_cancel_cutoff_hours, int) or isinstance(late_cancel_cutoff_hours, bool):
        raise bad_request("late_cancel_cutoff_hours must be an integer.")
    if late_cancel_cutoff_hours < 0:
        raise bad_request("late_cancel_cutoff_hours must be >= 0.")

    noshow_strike_window_days = body.get("noshow_strike_window_days", 90)
    if not isinstance(noshow_strike_window_days, int) or isinstance(noshow_strike_window_days, bool):
        raise bad_request("noshow_strike_window_days must be an integer.")

    noshow_strike_threshold = body.get("noshow_strike_threshold", 3)
    if not isinstance(noshow_strike_threshold, int) or isinstance(noshow_strike_threshold, bool):
        raise bad_request("noshow_strike_threshold must be an integer.")

    rec = {
        "name": name,
        "deposit_rate_pct": deposit_rate_pct,
        "late_cancel_cutoff_hours": late_cancel_cutoff_hours,
        "noshow_strike_window_days": noshow_strike_window_days,
        "noshow_strike_threshold": noshow_strike_threshold,
        "status": "OPEN",
    }
    stamp_create(rec)
    store.studios[rec["id"]] = rec
    return success_object(serialize.studio_out(rec), status=201)


@bp.route("/studios", methods=["GET"])
def list_studios():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = sort_by_created(list(store.studios.values()))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.studio_out(s) for s in page], limit, offset, total)


@bp.route("/studios/<sid>", methods=["GET"])
def get_studio(sid):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    s = get_studio_or_404(sid)
    return success_object(serialize.studio_out(s))


# --------------------------- ServiceType -----------------------------------
@bp.route("/service-types", methods=["POST"])
def create_service_type():
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    studio = get_studio_or_404(studio_id)

    code = body.get("code")
    if code not in ("FULL_SET", "FILL", "LIFT", "TINT"):
        raise bad_request("code must be one of FULL_SET, FILL, LIFT, TINT.")
    name = require_str(body, "name")
    duration_minutes = require_int(body, "duration_minutes")
    if duration_minutes <= 0:
        raise bad_request("duration_minutes must be greater than zero.")
    base_price_cents = require_int(body, "base_price_cents", minimum=0)
    credit_cost = require_int(body, "credit_cost", minimum=0)
    category = body.get("category")
    if category not in ("PREMIUM", "STANDARD"):
        raise bad_request("category must be PREMIUM or STANDARD.")
    requires_patch_test = body.get("requires_patch_test", True)
    if not isinstance(requires_patch_test, bool):
        raise bad_request("requires_patch_test must be a boolean.")

    rec = {
        "studio_id": studio["id"],
        "code": code,
        "name": name,
        "duration_minutes": duration_minutes,
        "base_price_cents": base_price_cents,
        "credit_cost": credit_cost,
        "category": category,
        "requires_patch_test": requires_patch_test,
        "active": True,
    }
    stamp_create(rec)
    store.service_types[rec["id"]] = rec
    return success_object(serialize.service_type_out(rec), status=201)


@bp.route("/service-types", methods=["GET"])
def list_service_types():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    from flask import request
    studio_id = request.args.get("studio_id")
    items = list(store.service_types.values())
    if studio_id is not None:
        items = [s for s in items if s["studio_id"] == studio_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.service_type_out(s) for s in page], limit, offset, total)


@bp.route("/service-types/<stid>", methods=["GET"])
def get_service_type(stid):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    st = get_service_type_or_404(stid)
    return success_object(serialize.service_type_out(st))


@bp.route("/service-types/<stid>/retire", methods=["POST"])
def retire_service_type(stid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    st = get_service_type_or_404(stid)
    st["active"] = False
    touch(st)
    return success_object(serialize.service_type_out(st))


# -------------------------- MembershipPlan ---------------------------------
@bp.route("/membership-plans", methods=["POST"])
def create_membership_plan():
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    studio = get_studio_or_404(studio_id)
    tier = body.get("tier")
    if tier not in ("ESSENTIAL", "PREMIER", "LUXE"):
        raise bad_request("tier must be one of ESSENTIAL, PREMIER, LUXE.")
    monthly_credit_allotment = require_int(body, "monthly_credit_allotment")
    if monthly_credit_allotment <= 0:
        raise bad_request("monthly_credit_allotment must be greater than zero.")
    monthly_fee_cents = require_int(body, "monthly_fee_cents", minimum=0)

    rollover_cap_multiplier = body.get("rollover_cap_multiplier", 1.0)
    if not isinstance(rollover_cap_multiplier, (int, float)) or isinstance(rollover_cap_multiplier, bool):
        raise bad_request("rollover_cap_multiplier must be a number.")
    if rollover_cap_multiplier < 0:
        raise bad_request("rollover_cap_multiplier must be >= 0.")

    loyalty_discount_pct = body.get("loyalty_discount_pct", 0.10)
    if not isinstance(loyalty_discount_pct, (int, float)) or isinstance(loyalty_discount_pct, bool):
        raise bad_request("loyalty_discount_pct must be a number.")
    if not (0 <= loyalty_discount_pct <= 1):
        raise bad_request("loyalty_discount_pct must be within [0, 1].")

    rec = {
        "studio_id": studio["id"],
        "tier": tier,
        "monthly_credit_allotment": monthly_credit_allotment,
        "monthly_fee_cents": monthly_fee_cents,
        "rollover_cap_multiplier": rollover_cap_multiplier,
        "loyalty_discount_pct": loyalty_discount_pct,
    }
    stamp_create(rec)
    store.membership_plans[rec["id"]] = rec
    return success_object(serialize.membership_plan_out(rec), status=201)


@bp.route("/membership-plans", methods=["GET"])
def list_membership_plans():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    from flask import request
    studio_id = request.args.get("studio_id")
    items = list(store.membership_plans.values())
    if studio_id is not None:
        items = [p for p in items if p["studio_id"] == studio_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.membership_plan_out(p) for p in page], limit, offset, total)


@bp.route("/membership-plans/<pid>", methods=["GET"])
def get_membership_plan(pid):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    p = store.membership_plans.get(pid)
    if not p:
        # No dedicated plan not-found error in the catalogue; treat as studio-
        # scoped reference miss is not applicable. Return a 404 envelope.
        raise errors.ApiError(errors.ERR_STUDIO_NOT_FOUND, 404, "Membership plan not found.")
    return success_object(serialize.membership_plan_out(p))
