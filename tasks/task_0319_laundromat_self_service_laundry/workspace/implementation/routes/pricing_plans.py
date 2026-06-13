"""PricingPlan endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db, stamp_create, touch
from errors import err, ERR_INVALID_STATE
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import (
    get_body,
    require_fields,
    require_int,
    require_str,
    parse_pagination,
    paginate,
    get_or_404,
)
from services.serialize import view

bp = Blueprint("pricing_plans", __name__)

# Plan input fields with (default, is_required) handling per PRD §3.1.
_PLAN_DEFAULTS = {
    "dry_block_minutes": 8,
    "surge_multiplier_bps": 10000,
    "surge_start_hour_utc": 16,
    "surge_end_hour_utc": 20,
    "wdf_minimum_cents": 1500,
    "reload_bonus_tier1_min_cents": 2000,
    "reload_bonus_tier1_bps": 500,
    "reload_bonus_tier2_min_cents": 5000,
    "reload_bonus_tier2_bps": 1000,
    "loyalty_cents_per_point": 100,
    "loyalty_redeem_threshold_points": 50,
}


@bp.post("/pricing-plans")
def create_plan():
    _, role = get_identity()
    require_roles(role, {"Manager"})
    body = get_body()
    require_fields(body, ["label", "wash_base_cents", "dry_base_cents_per_block", "wdf_rate_cents_per_lb"])

    label = require_str(body["label"], "label")
    wash_base = require_int(body["wash_base_cents"], "wash_base_cents", gt=0)
    dry_base = require_int(body["dry_base_cents_per_block"], "dry_base_cents_per_block", gt=0)
    wdf_rate = require_int(body["wdf_rate_cents_per_lb"], "wdf_rate_cents_per_lb", gt=0)

    plan = {
        "label": label,
        "wash_base_cents": wash_base,
        "dry_base_cents_per_block": dry_base,
        "wdf_rate_cents_per_lb": wdf_rate,
    }
    # Optional fields with declared defaults and constraints.
    for f, default in _PLAN_DEFAULTS.items():
        if f in body and body[f] is not None:
            val = body[f]
            if f == "dry_block_minutes":
                require_int(val, f, gt=0)
            elif f == "surge_multiplier_bps":
                require_int(val, f, minimum=10000)
            elif f in ("surge_start_hour_utc", "surge_end_hour_utc"):
                require_int(val, f, minimum=0, maximum=23)
            elif f in ("wdf_minimum_cents", "reload_bonus_tier1_min_cents",
                       "reload_bonus_tier1_bps", "reload_bonus_tier2_min_cents",
                       "reload_bonus_tier2_bps"):
                require_int(val, f, minimum=0)
            elif f in ("loyalty_cents_per_point", "loyalty_redeem_threshold_points"):
                require_int(val, f, gt=0)
            plan[f] = val
        else:
            plan[f] = default

    plan["status"] = "DRAFT"
    stamp_create(plan)
    with db.lock:
        db.pricing_plans[plan["id"]] = plan
    return object_response(view(plan), status=201)


@bp.get("/pricing-plans")
def list_plans():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant"})
    from flask import request
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(db.pricing_plans.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([view(p) for p in window], limit, offset, total)


@bp.get("/pricing-plans/<plan_id>")
def get_plan(plan_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant"})
    plan = get_or_404(db.pricing_plans, plan_id, "PricingPlan")
    return object_response(view(plan))


@bp.post("/pricing-plans/<plan_id>/activate")
def activate_plan(plan_id):
    _, role = get_identity()
    require_roles(role, {"Manager"})
    with db.lock:
        plan = get_or_404(db.pricing_plans, plan_id, "PricingPlan")
        # State precondition (PRD §3.1): plan must be DRAFT, and the surge/tier
        # invariants must hold; a plan failing the state precondition -> 409.
        if plan["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Plan is not DRAFT")
        if not (plan["surge_end_hour_utc"] > plan["surge_start_hour_utc"]):
            raise err(ERR_INVALID_STATE, "surge_end_hour_utc must be > surge_start_hour_utc")
        if not (plan["reload_bonus_tier2_min_cents"] >= plan["reload_bonus_tier1_min_cents"]):
            raise err(ERR_INVALID_STATE, "tier2 min must be >= tier1 min")
        # Cascade: retire any other currently-ACTIVE plan.
        for other in db.pricing_plans.values():
            if other["id"] != plan_id and other["status"] == "ACTIVE":
                other["status"] = "RETIRED"
                touch(other)
        plan["status"] = "ACTIVE"
        touch(plan)
    return object_response(view(plan))


@bp.post("/pricing-plans/<plan_id>/retire")
def retire_plan(plan_id):
    _, role = get_identity()
    require_roles(role, {"Manager"})
    with db.lock:
        plan = get_or_404(db.pricing_plans, plan_id, "PricingPlan")
        if plan["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Plan is not ACTIVE")
        plan["status"] = "RETIRED"
        touch(plan)
    return object_response(view(plan))
