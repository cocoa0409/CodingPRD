"""Quote endpoints (PRD §3.4)."""
from flask import Blueprint, request

import calculations as calc
import clock
import db
from common import (
    find_or_404,
    get_body,
    new_record,
    pagination,
    paginate,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_owner, require_role
from response import array_response, object_response

bp = Blueprint("quotes", __name__)


@bp.post("/quotes")
def create_quote():
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    body = get_body()
    enrollment_id = require_str(body, "enrollment_id")
    enr = find_or_404(db.enrollments, enrollment_id)

    # An enrollment must be READY_TO_QUOTE; an already-quoted enrollment cannot
    # back a second quote (PRD §3.4).
    if enr["status"] != "READY_TO_QUOTE":
        raise ApiError("ERR_ENROLLMENT_NOT_READY")

    plan = db.rate_plans[enr["rate_plan_id"]]

    locked = enr["provisional_risk_score"]
    multiplier = calc.risk_multiplier(locked)
    premium = calc.quoted_premium_cents(plan["base_premium_cents"], multiplier)

    created = clock.now()
    expires = clock.add_days(created, calc.QUOTE_VALIDITY_DAYS)

    rec = new_record(
        {
            "driver_id": enr["driver_id"],
            "enrollment_id": enr["id"],
            "rate_plan_id": enr["rate_plan_id"],
            "locked_risk_score": locked,
            "risk_multiplier": multiplier,
            "quoted_annual_premium_cents": premium,
            "expires_at": clock.format_iso(expires),
            "status": "OPEN",
        }
    )
    # created_at was stamped by new_record from the same clock instant; expires_at
    # is created_at + QUOTE_VALIDITY_DAYS.
    db.quotes[rec["id"]] = rec

    # Source enrollment transitions to terminal QUOTED (PRD §3.4).
    enr["status"] = "QUOTED"
    touch(enr)

    return object_response(serialize(rec), 201)


@bp.get("/quotes")
def list_quotes():
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    limit, offset = pagination()
    items = list(db.quotes.values())
    for key in ("driver_id", "enrollment_id", "rate_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [q for q in items if q[key] == val]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/quotes/<rid>")
def get_quote(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    rec = find_or_404(db.quotes, rid)
    return object_response(serialize(rec), 200)


@bp.post("/quotes/<rid>/decline")
def decline_quote(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    quote = find_or_404(db.quotes, rid)
    require_owner(role, user_id, quote["driver_id"])
    if quote["status"] != "OPEN":
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    quote["status"] = "DECLINED"
    touch(quote)
    return object_response(serialize(quote), 200)


@bp.post("/quotes/<rid>/expire")
def expire_quote(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    quote = find_or_404(db.quotes, rid)
    if clock.now() <= clock.parse_iso(quote["expires_at"]):
        raise ApiError("ERR_QUOTE_NOT_EXPIRED")
    quote["status"] = "EXPIRED"
    touch(quote)
    return object_response(serialize(quote), 200)
