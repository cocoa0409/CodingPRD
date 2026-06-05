"""Customs hold endpoints (PRD §3.5)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require
from response import ok_object
from services import serialize
from services.common import get_body, require_enum, require_present, stamp_create, touch
from services.lookups import fk_container, path_hold

bp = Blueprint("customs_holds", __name__)

HOLD_REASONS = {"INSPECTION", "DOCUMENTATION", "DUTY_UNPAID"}


@bp.post("/customs-holds")
@require("CustomsOfficer")
def place_hold():
    body = get_body()
    # FK existence (priority 4)
    container_id = require_present(body, "container_id")
    if not isinstance(container_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "container_id must be a string")
    container = fk_container(container_id)
    # shape (priority 5)
    reason = require_enum(body, "reason", HOLD_REASONS)
    # state (priority 7): container PENDING and not GATED_OUT
    if container["customs_status"] != "PENDING" or container["handling_status"] == "GATED_OUT":
        raise APIError(ERR_INVALID_STATE, 409, "container is not PENDING (or already gated out)")

    rec = stamp_create({
        "container_id": container_id,
        "reason": reason,
        "placed_at": db.clock_now(),
        "released_at": None,
        "status": "ACTIVE",
    })
    db.customs_holds[rec["id"]] = rec
    container["customs_status"] = "HELD"
    touch(container)
    return ok_object(serialize.customs_hold(rec), 201)


@bp.get("/customs-holds/<hid>")
@require("TerminalAdmin", "CustomsOfficer")
def get_hold(hid):
    rec = path_hold(hid)
    return ok_object(serialize.customs_hold(rec))


@bp.post("/customs-holds/<hid>/release")
@require("CustomsOfficer")
def release_hold(hid):
    hold = path_hold(hid)
    container = db.containers.get(hold["container_id"])
    # state (priority 7): hold ACTIVE and container HELD
    if hold["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "customs hold is not ACTIVE")
    if container is None or container["customs_status"] != "HELD":
        raise APIError(ERR_INVALID_STATE, 409, "container customs_status is not HELD")
    hold["status"] = "RELEASED"
    hold["released_at"] = db.clock_now()
    touch(hold)
    container["customs_status"] = "CLEARED"
    touch(container)
    return ok_object(serialize.customs_hold(hold))
