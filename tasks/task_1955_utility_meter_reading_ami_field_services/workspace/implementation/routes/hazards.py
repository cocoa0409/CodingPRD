"""HazardFlag endpoints: report (with merge), clear, renew, list/get."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, stamp_new, touch, now_dt
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION, ERR_HAZARD_FLAG_NOT_ACTIVE,
)
from middleware import require_roles, ALL_ROLES, body, req_str, req_enum
from response import success, list_response, created_sorted
from serializers import ser_hazard
from services.cascades import hazard_resolution_cascade
from util import fmt_dt, parse_dt

bp = Blueprint("hazards", __name__)

HAZARD_TTL_DAYS = 30


def get_flag(hid):
    h = db.hazards.get(hid)
    if not h:
        raise ApiError(ERR_NOT_FOUND, "HazardFlag not found", 404)
    return h


@bp.route("/hazard-flags", methods=["POST"])
def report():
    uid, _role = require_roles("FieldTechnician")
    data = body()
    account_id = req_str(data, "service_account_id")
    hazard_type = req_enum(
        data, "hazard_type", ("DOG", "ACCESS", "LOCKED_GATE", "CHEMICAL", "OTHER")
    )
    severity = req_enum(data, "severity", ("LOW", "HIGH"))
    if account_id not in db.accounts:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "ServiceAccount not found", 404)
    now = now_dt()
    existing = next(
        (h for h in db.hazards.values()
         if h["service_account_id"] == account_id
         and h["hazard_type"] == hazard_type
         and h["flag_status"] == "ACTIVE"),
        None,
    )
    if existing is not None:
        # interval-merge: no new row, 200 with the existing flag
        candidate = now + timedelta(days=HAZARD_TTL_DAYS)
        if candidate > parse_dt(existing["expires_at"]):
            existing["expires_at"] = fmt_dt(candidate)
        existing["reported_at"] = fmt_dt(now)
        existing["renewed_count"] += 1
        touch(existing)
        return success(ser_hazard(existing), code=200)
    rec = {
        "service_account_id": account_id,
        "hazard_type": hazard_type,
        "severity": severity,
        "flag_status": "ACTIVE",
        "reported_by_technician_id": uid,
        "reported_at": fmt_dt(now),
        "expires_at": fmt_dt(now + timedelta(days=HAZARD_TTL_DAYS)),
        "renewed_count": 0,
    }
    stamp_new(rec)
    db.hazards[rec["id"]] = rec
    return success(ser_hazard(rec), code=201)


@bp.route("/hazard-flags", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.hazards.values())
    for param in ("service_account_id", "reported_by_technician_id", "flag_status"):
        val = request.args.get(param)
        if val is not None:
            items = [h for h in items if h[param] == val]
    return list_response([ser_hazard(h) for h in created_sorted(items)])


@bp.route("/hazard-flags/<hid>", methods=["GET"])
def get_one(hid):
    require_roles(*ALL_ROLES)
    return success(ser_hazard(get_flag(hid)), code=200)


@bp.route("/hazard-flags/<hid>/clear", methods=["POST"])
def clear(hid):
    require_roles("FieldTechnician", "Dispatcher", "MeterOpsAdmin")
    h = get_flag(hid)
    if h["flag_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Hazard flag is not ACTIVE", 409)
    h["flag_status"] = "CLEARED"
    touch(h)
    hazard_resolution_cascade(h["service_account_id"], h["id"])
    return success(ser_hazard(h), code=200)


@bp.route("/hazard-flags/<hid>/renew", methods=["POST"])
def renew(hid):
    require_roles("FieldTechnician")
    h = get_flag(hid)
    if h["flag_status"] != "ACTIVE":
        raise ApiError(ERR_HAZARD_FLAG_NOT_ACTIVE, "Hazard flag is not ACTIVE", 409)
    now = now_dt()
    candidate = now + timedelta(days=HAZARD_TTL_DAYS)
    if candidate > parse_dt(h["expires_at"]):
        h["expires_at"] = fmt_dt(candidate)
    h["renewed_count"] += 1
    touch(h)
    return success(ser_hazard(h), code=200)
