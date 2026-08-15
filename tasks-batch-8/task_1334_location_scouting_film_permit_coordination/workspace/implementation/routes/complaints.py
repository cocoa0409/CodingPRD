"""Complaint endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_enum, optional_str,
    make_entity, touch, get_production, get_scoped,
    list_filtered, paginate, get_pagination_params,
    recompute_compliance, shut_down_shoot_day,
)
from datetime import timedelta

bp = Blueprint("complaints", __name__)


@bp.route("/productions/<pid>/complaints", methods=["POST"])
def create_complaint(pid):
    user_id, role = require_role("LocationManager", "FilmOffice", "OwnerRep")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["shoot_day_id", "category", "severity"])
    sd_id = require_str(payload, "shoot_day_id")
    sd = store.shoot_days.get(sd_id)
    if not sd or sd.get("production_id") != pid:
        raise ApiError(ERR_NOT_FOUND, "ShootDay not found", 404)
    filed_at = store.clock.now()
    response_due = filed_at + timedelta(hours=24)
    entity = make_entity({
        "production_id": pid,
        "shoot_day_id": sd_id,
        "category": require_enum(payload, "category", ["NOISE", "PARKING", "PROPERTY_DAMAGE", "HOURS_VIOLATION", "OTHER"]),
        "severity": require_enum(payload, "severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
        "filed_at": store.clock.now_iso(),
        "response_due_at": response_due.strftime("%Y-%m-%dT%H:%M:%S.") + f"{response_due.microsecond // 1000:03d}Z",
        "resolution_note": optional_str(payload, "resolution_note", ""),
        "status": "OPEN",
    })
    store.complaints[entity["id"]] = entity
    # Recompute compliance
    recompute_compliance(sd)
    touch(sd)
    # CRITICAL on IN_PROGRESS -> SHUT_DOWN cascade
    if entity["severity"] == "CRITICAL" and sd["status"] == "IN_PROGRESS":
        shut_down_shoot_day(sd)
    return success_object(entity, 201)


@bp.route("/productions/<pid>/complaints", methods=["GET"])
def list_complaints(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("shoot_day_id", "status", "severity"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.complaints, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/complaints/<rid>/acknowledge", methods=["POST"])
def acknowledge_complaint(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    c = get_scoped(store.complaints, rid, pid, "Complaint")
    if c["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Complaint is not OPEN", 409)
    c["status"] = "ACKNOWLEDGED"
    touch(c)
    return success_object(c)


@bp.route("/productions/<pid>/complaints/<rid>/resolve", methods=["POST"])
def resolve_complaint(pid, rid):
    user_id, role = require_role("LocationManager", "FilmOffice")
    p = get_production(pid)
    c = get_scoped(store.complaints, rid, pid, "Complaint")
    # LM resolves from ACKNOWLEDGED; FilmOffice resolves from ESCALATED
    if role == "LocationManager" and c["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE, "LocationManager can only resolve from ACKNOWLEDGED", 409)
    if role == "FilmOffice" and c["status"] != "ESCALATED":
        raise ApiError(ERR_INVALID_STATE, "FilmOffice can only resolve from ESCALATED", 409)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["resolution_note"])
    note = require_str(payload, "resolution_note")
    if not note or note.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST, "resolution_note must be non-empty", 400)
    c["resolution_note"] = note
    c["status"] = "RESOLVED"
    touch(c)
    return success_object(c)
