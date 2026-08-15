"""Weather advisories: create (posture recompute), list/get, cancel (PRD 3.4)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_ADVISORY_WINDOW_INVALID
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, exist_body_fks, pagination_params, paginate, apply_filters, parse_dt

bp = Blueprint("advisories", __name__, url_prefix="/port-ops")


@bp.route("/weather-advisories", methods=["POST"])
def create_advisory():
    authenticate({"PortAuthorityAdmin"})
    body = body_json()
    exist_body_fks(body, {"terminal_id": ("terminals", "terminal")})
    check_shape(body, {
        "terminal_id": {"type": "string", "required": True},
        "severity": {"type": "enum", "required": True, "values": {"WATCH", "WARNING", "EMERGENCY"}},
        "window_start": {"type": "datetime", "required": True},
        "window_end": {"type": "datetime", "required": True},
    })
    # Priority 13: window sanity -- end strictly after start.
    if not parse_dt(body["window_end"], "window_end") > parse_dt(body["window_start"], "window_start"):
        raise ApiError(ERR_ADVISORY_WINDOW_INVALID, 422,
                       "window_end must be strictly later than window_start")
    adv = db.new_entity("weather_advisories", {
        "terminal_id": body["terminal_id"],
        "severity": body["severity"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "ACTIVE",
    })
    return success_obj(db.public(adv), code=201)


@bp.route("/weather-advisories", methods=["GET"])
def list_advisories():
    authenticate(ANY)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("weather_advisories"), ["terminal_id", "status", "severity"])
    page, total, has_more = paginate([db.public(a) for a in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/weather-advisories/<adv_id>", methods=["GET"])
def get_advisory(adv_id):
    authenticate(ANY)
    adv = db.get("weather_advisories", adv_id)
    if adv is None:
        raise ApiError(ERR_NOT_FOUND, 404, "weather advisory not found")
    return success_obj(db.public(adv))


@bp.route("/weather-advisories/<adv_id>/cancel", methods=["POST"])
def cancel_advisory(adv_id):
    authenticate({"PortAuthorityAdmin"})
    adv = db.get("weather_advisories", adv_id)
    if adv is None:
        raise ApiError(ERR_NOT_FOUND, 404, "weather advisory not found")
    if adv["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "cancel requires status ACTIVE")
    adv["status"] = "CANCELLED"
    db.touch(adv)
    return success_obj(db.public(adv))
