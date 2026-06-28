"""Membership-plan endpoints (PRD §3.4)."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    get_body, require_enum, require_int_min, opt_int_min, opt_bool,
    parse_pagination, sort_by_created, paginate, stamp_new,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_membership_plan
from services.lookups import get_plan_or_404

bp = Blueprint("membership_plans", __name__)

PLAN_TIERS = {"BASE", "PLUS", "ELITE"}


@bp.post("/membership-plans")
@require_roles("PlatformAdmin")
def create_plan():
    body = get_body()
    tier = require_enum(body, "tier", PLAN_TIERS)
    monthly_fee_cents = require_int_min(body, "monthly_fee_cents", 0)
    monthly_credit_grant = require_int_min(body, "monthly_credit_grant", 0)
    rollover_cap = opt_int_min(body, "rollover_cap", 0, 0)
    late_cancel_fee_waived = opt_bool(body, "late_cancel_fee_waived", False)
    active = opt_bool(body, "active", True)
    # tier is unique across plans (scaffold §1.1).
    for p in db.membership_plans.values():
        if p["tier"] == tier:
            raise errors.invalid_request("Plan tier must be unique: " + tier)
    plan = stamp_new({
        "tier": tier,
        "monthly_fee_cents": monthly_fee_cents,
        "monthly_credit_grant": monthly_credit_grant,
        "rollover_cap": rollover_cap,
        "late_cancel_fee_waived": late_cancel_fee_waived,
        "active": active,
    })
    db.membership_plans[plan["id"]] = plan
    return success(serialize_membership_plan(plan), 201)


@bp.get("/membership-plans")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def list_plans():
    limit, offset = parse_pagination()
    active = request.args.get("active")
    items = list(db.membership_plans.values())
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success(
        [serialize_membership_plan(p) for p in page], limit, offset, total)


@bp.get("/membership-plans/<plan_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def get_plan(plan_id):
    plan = get_plan_or_404(plan_id)
    return success(serialize_membership_plan(plan), 200)
