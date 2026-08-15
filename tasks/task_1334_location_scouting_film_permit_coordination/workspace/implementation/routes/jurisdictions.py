"""Jurisdiction endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND
from db import store
from services.helpers import (
    require_fields, require_int, require_str, optional_int,
    make_entity, touch, get_jurisdiction, list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("jurisdictions", __name__)


@bp.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    user_id, role = require_role("FilmOffice")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["code", "name", "lead_time_business_days",
                             "notification_lead_calendar_days", "notification_radius_ft",
                             "base_fee_cents", "per_day_fee_cents", "per_lane_fee_cents",
                             "large_cast_threshold", "large_cast_multiplier_bps",
                             "min_liability_limit_cents", "police_monitor_lane_threshold"])
    code = require_str(payload, "code")
    # Check unique code
    for j in store.jurisdictions.values():
        if j.get("code") == code:
            raise ApiError(ERR_INVALID_REQUEST, f"Jurisdiction code '{code}' already exists", 400)
    holidays = payload.get("holidays", [])
    if not isinstance(holidays, list):
        raise ApiError(ERR_INVALID_REQUEST, "holidays must be an array", 400)
    entity = make_entity({
        "code": code,
        "name": require_str(payload, "name"),
        "lead_time_business_days": require_int(payload, "lead_time_business_days"),
        "notification_lead_calendar_days": require_int(payload, "notification_lead_calendar_days"),
        "notification_radius_ft": require_int(payload, "notification_radius_ft"),
        "base_fee_cents": require_int(payload, "base_fee_cents"),
        "per_day_fee_cents": require_int(payload, "per_day_fee_cents"),
        "per_lane_fee_cents": require_int(payload, "per_lane_fee_cents"),
        "large_cast_threshold": require_int(payload, "large_cast_threshold"),
        "large_cast_multiplier_bps": require_int(payload, "large_cast_multiplier_bps"),
        "min_liability_limit_cents": require_int(payload, "min_liability_limit_cents"),
        "police_monitor_lane_threshold": require_int(payload, "police_monitor_lane_threshold"),
        "holidays": holidays,
        "status": "ACTIVE",
    })
    store.jurisdictions[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/jurisdictions/<jid>", methods=["GET"])
def get_jurisdiction_by_id(jid):
    user_id, role = require_role(*ALL_ROLES)
    j = get_jurisdiction(jid)
    return success_object(j)


@bp.route("/jurisdictions", methods=["GET"])
def list_jurisdictions():
    user_id, role = require_role(*ALL_ROLES)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    code = request.args.get("code")
    if code:
        filters["code"] = code
    items = list_filtered(store.jurisdictions, filters)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/jurisdictions/<jid>/suspend", methods=["POST"])
def suspend_jurisdiction(jid):
    user_id, role = require_role("FilmOffice")
    j = get_jurisdiction(jid)
    if j["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Jurisdiction is not ACTIVE", 409)
    j["status"] = "SUSPENDED"
    touch(j)
    return success_object(j)
