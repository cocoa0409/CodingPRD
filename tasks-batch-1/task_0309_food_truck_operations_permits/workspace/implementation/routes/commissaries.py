"""Commissary endpoints (PRD §3.1)."""

from flask import Blueprint

import errors
import serializers
import services
from db import db
from errors import err
from helpers import get_body, require_str, require_state_code, get_pagination, paginate
from lookups import get_commissary
from middleware import require_user_context, require_role
from response import ok_object, ok_array

bp = Blueprint("commissaries", __name__)

WRITE_ROLES = {"Dispatcher", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}


@bp.post("/commissaries")
def create_commissary():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    name = require_str(body, "name")
    state_code = require_state_code(body, "state_code")
    rec = db.new_record({
        "name": name,
        "state_code": state_code,
        "status": "ACTIVE",
    })
    db.commissaries[rec["id"]] = rec
    return ok_object(serializers.commissary(rec), 201)


@bp.get("/commissaries")
def list_commissaries():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    window, total = paginate(list(db.commissaries.values()), limit, offset)
    return ok_array([serializers.commissary(r) for r in window], limit, offset, total)


@bp.get("/commissaries/<commissary_id>")
def get_commissary_route(commissary_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_commissary(commissary_id)
    return ok_object(serializers.commissary(rec))


@bp.post("/commissaries/<commissary_id>/suspend")
def suspend_commissary(commissary_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_commissary(commissary_id)
    if rec["status"] != "ACTIVE":
        raise err(errors.ERR_COMMISSARY_NOT_ACTIVE, "Commissary is not ACTIVE")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    # Recompute operability of every truck docked here (cascades on grounding).
    for truck in list(db.trucks.values()):
        if truck["commissary_id"] == rec["id"]:
            services.recompute_operability(truck)
    return ok_object(serializers.commissary(rec))


@bp.post("/commissaries/<commissary_id>/reinstate")
def reinstate_commissary(commissary_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_commissary(commissary_id)
    if rec["status"] != "SUSPENDED":
        raise err(errors.ERR_COMMISSARY_NOT_SUSPENDED, "Commissary is not SUSPENDED")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    for truck in list(db.trucks.values()):
        if truck["commissary_id"] == rec["id"]:
            services.recompute_operability(truck)
    return ok_object(serializers.commissary(rec))
