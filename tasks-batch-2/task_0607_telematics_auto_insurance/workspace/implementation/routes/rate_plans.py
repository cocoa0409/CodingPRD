"""Rate plan endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from common import (
    find_or_404,
    get_body,
    new_record,
    pagination,
    paginate,
    require_int,
    require_number,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_role
from response import array_response, object_response

bp = Blueprint("rate_plans", __name__)

ALL_ROLES = ["UnderwritingOps", "DriverUser", "ClaimsAdjuster"]


def _validate_non_negative_int(body, key):
    v = require_int(body, key)
    if v < 0:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be >= 0.")
    return v


def _validate_non_negative_number(body, key):
    v = require_number(body, key)
    if v < 0:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be >= 0.")
    return v


@bp.post("/rate-plans")
def create_rate_plan():
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    body = get_body()
    rec = new_record(
        {
            "name": require_str(body, "name"),
            "state_code": require_str(body, "state_code"),
            "base_premium_cents": _validate_non_negative_int(body, "base_premium_cents"),
            "per_mile_rate_cents": _validate_non_negative_number(body, "per_mile_rate_cents"),
            "included_miles_per_period": _validate_non_negative_int(
                body, "included_miles_per_period"
            ),
            "hard_brake_weight": require_number(body, "hard_brake_weight"),
            "speeding_weight": require_number(body, "speeding_weight"),
            "phone_use_weight": require_number(body, "phone_use_weight"),
            "status": "ACTIVE",
        }
    )
    db.rate_plans[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.get("/rate-plans")
def list_rate_plans():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    limit, offset = pagination()
    state_code = request.args.get("state_code")
    items = list(db.rate_plans.values())
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/rate-plans/<rid>")
def get_rate_plan(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    rec = find_or_404(db.rate_plans, rid)
    return object_response(serialize(rec), 200)


@bp.post("/rate-plans/<rid>/retire")
def retire_rate_plan(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    rec = find_or_404(db.rate_plans, rid)
    rec["status"] = "RETIRED"
    touch(rec)
    return object_response(serialize(rec), 200)
