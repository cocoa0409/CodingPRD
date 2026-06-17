"""RainCheck endpoints (PRD §3.8) and the logical-clock endpoint (PRD §3.9)."""
from flask import Blueprint, request

import errors
from db import db, touch, now_iso
from errors import ApiError
from middleware import authenticate, require_role
from response import success, list_success
from services import serialize
from services.common import get_json_body, parse_pagination, paginate, parse_datetime
from services.lookup import get_rain_check

bp = Blueprint("rainchecks", __name__)


@bp.route("/rain-checks/<rid>", methods=["GET"])
def get_rain_check_route(rid):
    _, role = authenticate()
    require_role(role, {"Guest", "FinanceClerk", "ParkManager"})
    rec = get_rain_check(rid)
    return success(serialize.rain_check(rec))


@bp.route("/rain-checks", methods=["GET"])
def list_rain_checks():
    _, role = authenticate()
    require_role(role, {"Guest", "FinanceClerk", "ParkManager"})
    limit, offset = parse_pagination()
    rows = list(db.rain_checks.values())
    guest_id = request.args.get("guest_id")
    park_id = request.args.get("park_id")
    status = request.args.get("status")
    if guest_id is not None:
        rows = [r for r in rows if r["guest_id"] == guest_id]
    if park_id is not None:
        rows = [r for r in rows if r["park_id"] == park_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.rain_check(r) for r in page], limit, offset, total)


@bp.route("/rain-checks/<rid>/settle", methods=["POST"])
def settle_rain_check(rid):
    _, role = authenticate()
    require_role(role, {"FinanceClerk"})
    rec = get_rain_check(rid)
    if rec["status"] != "ISSUED":
        raise ApiError(errors.ERR_RAINCHECK_NOT_ISSUED, 409,
                       "settle requires rain-check status ISSUED")
    rec["status"] = "SETTLED"
    touch(rec)
    guest = db.guests.get(rec["guest_id"]) if rec["guest_id"] else None
    if guest is not None:
        guest["wallet_credit_cents"] += rec["value_cents"]
        touch(guest)
    return success(serialize.rain_check(rec))


@bp.route("/rain-checks/<rid>/expire", methods=["POST"])
def expire_rain_check(rid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    rec = get_rain_check(rid)
    if rec["status"] != "ISSUED":
        raise ApiError(errors.ERR_RAINCHECK_NOT_ISSUED, 409,
                       "expire requires rain-check status ISSUED")
    rec["status"] = "EXPIRED"
    touch(rec)
    return success(serialize.rain_check(rec))


# ---- Logical clock ----
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = get_json_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: to_iso8601")
    # Validate it parses as ISO 8601.
    parse_datetime(body["to_iso8601"], "to_iso8601")
    db.clock["current_utc"] = body["to_iso8601"]
    return success(serialize.clock_state(db.clock))
