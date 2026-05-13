"""Studio + TimeSlotConfig endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION_FAILED, raise_err)
from middleware import (
    require_auth, require_role, parse_pagination, paginate, occ_check)
from response import success


bp = Blueprint("studios", __name__, url_prefix="/live-schedule/studios")


_STUDIO_STATUSES = {"OPEN", "RESTRICTED", "UNDER_MAINTENANCE", "CLOSED"}
_STUDIO_TYPES = {"SELF_OPERATED", "PARTNER"}
_SLOT_TIERS = {"S", "A", "B", "C"}


@bp.post("")
def create_studio():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = request.get_json(silent=True) or {}
    for key in ("name", "location", "equipment_inventory",
                "capacity", "studio_type", "slot_tier",
                "base_hour_price_cents"):
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")
    if not isinstance(body["capacity"], int) or body["capacity"] < 1:
        raise_err(ERR_VALIDATION_FAILED, "capacity must be >=1")
    if body["studio_type"] not in _STUDIO_TYPES:
        raise_err(ERR_VALIDATION_FAILED, "Invalid studio_type")
    if body["slot_tier"] not in _SLOT_TIERS:
        raise_err(ERR_VALIDATION_FAILED, "Invalid slot_tier")
    if not isinstance(body["base_hour_price_cents"], int) or body["base_hour_price_cents"] < 0:
        raise_err(ERR_VALIDATION_FAILED, "base_hour_price_cents must be >=0")

    payload = {
        "name": body["name"],
        "location": body["location"],
        "equipment_inventory": list(body["equipment_inventory"]),
        "capacity": int(body["capacity"]),
        "studio_type": body["studio_type"],
        "slot_tier": body["slot_tier"],
        "base_hour_price_cents": int(body["base_hour_price_cents"]),
        "status": "OPEN",
    }
    studio = db.create_entity("studios", payload)
    return success(studio, http_status=201)


@bp.patch("/<sid>")
def update_studio(sid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    entity = db.raw_get("studios", sid)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "Studio not found")
    body = request.get_json(silent=True) or {}
    occ_check(entity, body)

    updates = {}
    if "status" in body:
        if body["status"] not in _STUDIO_STATUSES:
            raise_err(ERR_VALIDATION_FAILED, "Invalid status")
        updates["status"] = body["status"]
    if "capacity" in body:
        if not isinstance(body["capacity"], int) or body["capacity"] < 1:
            raise_err(ERR_VALIDATION_FAILED, "capacity must be >=1")
        updates["capacity"] = body["capacity"]

    def mutate(s):
        s.update(updates)

    updated = db.update_entity("studios", sid, mutate)
    return success(updated)


# ---------------------------------------------------------------------------
# Time slots
# ---------------------------------------------------------------------------

_SLOT_KINDS = {"AVAILABLE", "MAINTENANCE"}


@bp.post("/<studio_id>/time-slots")
def create_time_slot(studio_id):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    if db.raw_get("studios", studio_id) is None:
        raise_err(ERR_NOT_FOUND, "Studio not found")
    body = request.get_json(silent=True) or {}
    for key in ("kind", "starts_at", "ends_at"):
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")
    if body["kind"] not in _SLOT_KINDS:
        raise_err(ERR_VALIDATION_FAILED, "Invalid kind")
    payload = {
        "studio_id": studio_id,
        "kind": body["kind"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "weekday_mask": int(body.get("weekday_mask", 0)),
    }
    config = db.create_entity("time_slot_configs", payload)
    return success(config, http_status=201)


@bp.get("/<studio_id>/time-slots")
def list_time_slots(studio_id):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer", "Streamer"])
    if db.raw_get("studios", studio_id) is None:
        raise_err(ERR_NOT_FOUND, "Studio not found")
    limit, offset = parse_pagination()
    items = db.list_entities(
        "time_slot_configs",
        predicate=lambda x: x.get("studio_id") == studio_id,
    )
    window, pagination = paginate(items, limit, offset)
    return success(window, pagination=pagination, response_type="array")
