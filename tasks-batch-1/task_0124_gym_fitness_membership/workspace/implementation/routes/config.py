"""MembershipPlan and Location endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
import lookups
import models
from middleware import authenticate, require_role
from response import success
from util import require_str, require_int, optional_number

bp = Blueprint("config", __name__)

PLAN_TIERS = {"BASIC", "PLUS", "ELITE"}


@bp.route("/membership-plans", methods=["POST"])
def create_plan():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    body = request.get_json(silent=True) or {}

    tier = require_str(body, "tier")
    if tier not in PLAN_TIERS:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "tier must be one of BASIC, PLUS, ELITE")
    monthly = require_int(body, "monthly_dues_cents", minimum=0)
    credits = require_int(body, "included_class_credits", minimum=0)
    pt_discount = optional_number(body, "pt_discount_pct", minimum=0.0, maximum=0.5, default=0)
    term_months = require_int(body, "contract_term_months", minimum=1)
    etf = require_int(body, "early_termination_fee_cents", minimum=0)
    max_freeze = require_int(body, "max_freeze_days_per_term", minimum=0)
    guest_passes = require_int(body, "guest_passes_per_cycle", minimum=0)

    # tier unique among non-archived plans (SCAFFOLD entity constraint).
    for p in db.store.membership_plans.values():
        if not p["archived"] and p["tier"] == tier:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "tier must be unique among non-archived plans")

    rec = models.stamp_new({
        "tier": tier,
        "monthly_dues_cents": monthly,
        "included_class_credits": credits,
        "pt_discount_pct": pt_discount,
        "contract_term_months": term_months,
        "early_termination_fee_cents": etf,
        "max_freeze_days_per_term": max_freeze,
        "guest_passes_per_cycle": guest_passes,
        "archived": False,
    })
    db.store.membership_plans[rec["id"]] = rec
    return success(models.serialize_plan(rec), status=201)


@bp.route("/membership-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_plan(plan_id)
    return success(models.serialize_plan(rec), status=200)


@bp.route("/locations", methods=["POST"])
def create_location():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    body = request.get_json(silent=True) or {}

    name = require_str(body, "name")
    cap = require_int(body, "occupancy_cap", minimum=1)

    rec = models.stamp_new({
        "name": name,
        "occupancy_cap": cap,
    })
    db.store.locations[rec["id"]] = rec
    return success(models.serialize_location(rec), status=201)


@bp.route("/locations/<location_id>", methods=["GET"])
def get_location(location_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_location(location_id)
    return success(models.serialize_location(rec), status=200)
