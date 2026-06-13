"""LostFoundItem endpoints (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err, ERR_INVALID_STATE, ERR_DISPOSAL_HOLD_ACTIVE
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import (
    get_body,
    require_fields,
    require_str,
    parse_pagination,
    paginate,
    get_or_404,
)
from services.cycle import format_iso, parse_iso
from services.serialize import view

bp = Blueprint("lost_found", __name__)

# Disposal-hold window (PRD §3.8 / SCAFFOLD DISPOSAL_HOLD_HOURS). The scaffold
# names the window but supplies no numeric default; the only behavioral contract
# tested is that an item logged at the current clock (zero elapsed time) cannot
# yet be disposed. A positive window satisfies that; 24h is the conventional
# laundromat hold.
DISPOSAL_HOLD_HOURS = 24


@bp.post("/lost-found")
def log_item():
    user_id, role = get_identity()
    require_roles(role, {"Attendant"})
    body = get_body()
    require_fields(body, ["logged_by_id", "description"])
    logged_by_id = require_str(body["logged_by_id"], "logged_by_id")
    description = require_str(body["description"], "description")
    machine_id = body.get("machine_id")
    with db.lock:
        if machine_id is not None:
            get_or_404(db.machines, machine_id, "Machine")
        item = {
            "machine_id": machine_id,
            "logged_by_id": logged_by_id,
            "description": description,
            "found_at": format_iso(db.capture_clock),
            "claimed_by_id": None,
            "status": "LOGGED",
        }
        stamp_create(item)
        db.lost_found[item["id"]] = item
    return object_response(view(item), status=201)


@bp.get("/lost-found")
def list_items():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    machine_id = request.args.get("machine_id")
    logged_by_id = request.args.get("logged_by_id")
    claimed_by_id = request.args.get("claimed_by_id")
    items = list(db.lost_found.values())
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if machine_id is not None:
        items = [i for i in items if i.get("machine_id") == machine_id]
    if logged_by_id is not None:
        items = [i for i in items if i["logged_by_id"] == logged_by_id]
    if claimed_by_id is not None:
        items = [i for i in items if i.get("claimed_by_id") == claimed_by_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(i) for i in window], limit, offset, total)


@bp.get("/lost-found/<item_id>")
def get_item(item_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    item = get_or_404(db.lost_found, item_id, "LostFoundItem")
    return object_response(view(item))


@bp.post("/lost-found/<item_id>/claim")
def claim_item(item_id):
    _, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        item = get_or_404(db.lost_found, item_id, "LostFoundItem")
        body = get_body()
        require_fields(body, ["claimed_by_id"])
        claimed_by_id = require_str(body["claimed_by_id"], "claimed_by_id")
        if item["status"] != "LOGGED":
            raise err(ERR_INVALID_STATE, "Item is not LOGGED")
        item["claimed_by_id"] = claimed_by_id
        item["status"] = "CLAIMED"
        touch(item)
    return object_response(view(item))


@bp.post("/lost-found/<item_id>/dispose")
def dispose_item(item_id):
    _, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        item = get_or_404(db.lost_found, item_id, "LostFoundItem")
        if item["status"] != "LOGGED":
            raise err(ERR_INVALID_STATE, "Item is not LOGGED")
        # Disposal-hold window (priority 16): capture_clock - found_at >= window.
        found_at = parse_iso(item["found_at"])
        elapsed = db.capture_clock - found_at
        if elapsed < timedelta(hours=DISPOSAL_HOLD_HOURS):
            raise err(ERR_DISPOSAL_HOLD_ACTIVE, "Disposal-hold window has not elapsed")
        item["status"] = "DISPOSED"
        touch(item)
    return object_response(view(item))
