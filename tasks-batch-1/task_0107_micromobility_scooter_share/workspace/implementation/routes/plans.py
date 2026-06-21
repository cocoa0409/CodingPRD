"""Plan endpoints (PRD §3.1).

POST /api/plans                — PlatformAdmin
GET  /api/plans/{id}           — PlatformAdmin, Rider
GET  /api/plans                — PlatformAdmin, Rider
"""
from flask import Blueprint, request

import errors
from db import db, stamp_new
from middleware import authenticate, require_role
from response import success
from util import (
    get_json_body, require_fields, require_enum, require_int, require_number,
    require_bool, public, parse_pagination, paginate,
)

bp = Blueprint("plans", __name__)

PLAN_CODES = {"STANDARD", "LOW_INCOME"}


@bp.post("/api/plans")
def create_plan():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})

    body = get_json_body()
    # State-machine legality precedes field-shape (PRD §2.8); no state gate here.
    require_fields(body, ["code", "unlock_fee_cents", "per_minute_cents", "daily_cap_cents"])
    require_enum(body["code"], PLAN_CODES, "code")
    require_int(body["unlock_fee_cents"], "unlock_fee_cents", minimum=0)
    require_int(body["per_minute_cents"], "per_minute_cents", minimum=0)
    require_int(body["daily_cap_cents"], "daily_cap_cents", minimum=0)

    discount = body.get("slow_zone_discount_pct", 0)
    require_number(discount, "slow_zone_discount_pct", minimum=0, maximum=1)
    active = body.get("active", True)
    require_bool(active, "active")

    # Uniqueness of code across plans (PRD §3.1). Treated as a field-level
    # validation failure (ERR_INVALID_REQUEST).
    for p in db.plans.values():
        if p["code"] == body["code"]:
            raise errors.invalid_request(f"Plan code {body['code']} already exists")

    plan = {
        "code": body["code"],
        "unlock_fee_cents": body["unlock_fee_cents"],
        "per_minute_cents": body["per_minute_cents"],
        "daily_cap_cents": body["daily_cap_cents"],
        "slow_zone_discount_pct": discount,
        "active": active,
    }
    stamp_new(plan)
    db.plans[plan["id"]] = plan
    return success(public(plan), status=201)


@bp.get("/api/plans/<plan_id>")
def get_plan(plan_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    plan = db.plans.get(plan_id)
    if plan is None:
        raise errors.not_found("Plan not found")
    return success(public(plan))


@bp.get("/api/plans")
def list_plans():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    limit, offset = parse_pagination()

    rows = list(db.plans.values())
    code = request.args.get("code")
    if code is not None:
        rows = [r for r in rows if r["code"] == code]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)
