"""Studio bootstrap + inventory (Room, Engineer, GearItem) + Client routes."""
from flask import Blueprint

from db import db
from errors import err
from middleware import get_principal, require_roles
from helpers import (
    get_json_body, require_str, optional_str, require_int, optional_int,
    require_number, optional_number, optional_bool, require_enum,
    get_pagination, paginate, get_or_404, stamp_common,
)
from response import success_object, success_array
from serialize import public, public_list

bp = Blueprint("inventory", __name__)


# ---------------------------------------------------------------------------
# Studio
# ---------------------------------------------------------------------------

@bp.route("/studio", methods=["POST"])
def create_studio():
    # Bootstrap is deliberately open (PRD §2.1): callable without credentials so
    # a brand-new studio can exist before any principal does.
    principal = get_principal(open_endpoint=True)
    require_roles(principal, {"StudioManager", "Anonymous"})
    body = get_json_body()
    name = require_str(body, "name")
    timezone = optional_str(body, "timezone", "UTC")
    deposit_pct = optional_number(body, "deposit_pct", 0.30)
    overtime_multiplier = optional_number(body, "overtime_multiplier", 1.5)
    overtime_grace_minutes = optional_int(body, "overtime_grace_minutes", 10)
    cancellation_tier_hours = optional_int(body, "cancellation_tier_hours", 48)
    late_cancel_fee_pct = optional_number(body, "late_cancel_fee_pct", 0.50)

    # Semantic bounds (ERR_VALIDATION, PRD §3.1)
    if not (deposit_pct > 0 and deposit_pct <= 1):
        raise err("ERR_VALIDATION", "deposit_pct must be in (0, 1]")
    if not (overtime_multiplier >= 1):
        raise err("ERR_VALIDATION", "overtime_multiplier must be >= 1")
    if not (overtime_grace_minutes >= 0):
        raise err("ERR_VALIDATION", "overtime_grace_minutes must be >= 0")
    if not (cancellation_tier_hours >= 0):
        raise err("ERR_VALIDATION", "cancellation_tier_hours must be >= 0")
    if not (0 <= late_cancel_fee_pct <= 1):
        raise err("ERR_VALIDATION", "late_cancel_fee_pct must be in [0, 1]")

    studio = {
        "name": name,
        "timezone": timezone,
        "deposit_pct": deposit_pct,
        "overtime_multiplier": overtime_multiplier,
        "overtime_grace_minutes": overtime_grace_minutes,
        "cancellation_tier_hours": cancellation_tier_hours,
        "late_cancel_fee_pct": late_cancel_fee_pct,
    }
    stamp_common(studio)
    db.studios[studio["id"]] = studio
    return success_object(public(studio), status=201)


@bp.route("/studio/<sid>", methods=["GET"])
def get_studio(sid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    studio = get_or_404(db.studios, sid, "studio")
    return success_object(public(studio))


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------

@bp.route("/studio/rooms", methods=["POST"])
def create_room():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    name = require_str(body, "name")
    hourly_rate_cents = require_int(body, "hourly_rate_cents")
    block_rate_cents = require_int(body, "block_rate_cents")
    block_hours = optional_int(body, "block_hours", 8)
    turnaround_minutes = optional_int(body, "turnaround_minutes", 30)

    get_or_404(db.studios, studio_id, "studio")

    if hourly_rate_cents < 0:
        raise err("ERR_VALIDATION", "hourly_rate_cents must be >= 0")
    if block_rate_cents < 0:
        raise err("ERR_VALIDATION", "block_rate_cents must be >= 0")
    if block_hours < 1:
        raise err("ERR_VALIDATION", "block_hours must be >= 1")
    if turnaround_minutes < 0:
        raise err("ERR_VALIDATION", "turnaround_minutes must be >= 0")

    room = {
        "studio_id": studio_id,
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
        "block_rate_cents": block_rate_cents,
        "block_hours": block_hours,
        "turnaround_minutes": turnaround_minutes,
        "status": "OPEN",
    }
    stamp_common(room)
    db.rooms[room["id"]] = room
    return success_object(public(room), status=201)


@bp.route("/studio/rooms/<rid>", methods=["GET"])
def get_room(rid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    room = get_or_404(db.rooms, rid, "room")
    return success_object(public(room))


@bp.route("/studio/rooms", methods=["GET"])
def list_rooms():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    from flask import request
    studio_id = request.args.get("studio_id")
    rooms = list(db.rooms.values())
    if studio_id is not None:
        rooms = [r for r in rooms if r["studio_id"] == studio_id]
    limit, offset = get_pagination()
    page, total = paginate(rooms, limit, offset)
    return success_array(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Engineer
# ---------------------------------------------------------------------------

@bp.route("/studio/engineers", methods=["POST"])
def create_engineer():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    full_name = require_str(body, "full_name")
    tier = require_enum(body, "tier", {"ASSISTANT", "STAFF", "SENIOR"})
    hourly_rate_cents = require_int(body, "hourly_rate_cents")
    active = optional_bool(body, "active", True)

    get_or_404(db.studios, studio_id, "studio")
    if hourly_rate_cents < 0:
        raise err("ERR_VALIDATION", "hourly_rate_cents must be >= 0")

    engineer = {
        "studio_id": studio_id,
        "full_name": full_name,
        "tier": tier,
        "hourly_rate_cents": hourly_rate_cents,
        "active": active,
    }
    stamp_common(engineer)
    db.engineers[engineer["id"]] = engineer
    return success_object(public(engineer), status=201)


@bp.route("/studio/engineers/<eid>", methods=["GET"])
def get_engineer(eid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    engineer = get_or_404(db.engineers, eid, "engineer")
    return success_object(public(engineer))


@bp.route("/studio/engineers", methods=["GET"])
def list_engineers():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    from flask import request
    studio_id = request.args.get("studio_id")
    engineers = list(db.engineers.values())
    if studio_id is not None:
        engineers = [e for e in engineers if e["studio_id"] == studio_id]
    limit, offset = get_pagination()
    page, total = paginate(engineers, limit, offset)
    return success_array(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# GearItem
# ---------------------------------------------------------------------------

@bp.route("/studio/gear-items", methods=["POST"])
def create_gear_item():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    name = require_str(body, "name")
    total_units = require_int(body, "total_units")
    daily_rate_cents = require_int(body, "daily_rate_cents")
    requires_engineer = optional_bool(body, "requires_engineer", False)

    get_or_404(db.studios, studio_id, "studio")
    if total_units < 1:
        raise err("ERR_VALIDATION", "total_units must be >= 1")
    if daily_rate_cents < 0:
        raise err("ERR_VALIDATION", "daily_rate_cents must be >= 0")

    gear = {
        "studio_id": studio_id,
        "name": name,
        "total_units": total_units,
        "daily_rate_cents": daily_rate_cents,
        "requires_engineer": requires_engineer,
    }
    stamp_common(gear)
    db.gear_items[gear["id"]] = gear
    return success_object(public(gear), status=201)


@bp.route("/studio/gear-items/<gid>", methods=["GET"])
def get_gear_item(gid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    gear = get_or_404(db.gear_items, gid, "gear item")
    return success_object(public(gear))


@bp.route("/studio/gear-items", methods=["GET"])
def list_gear_items():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    from flask import request
    studio_id = request.args.get("studio_id")
    gears = list(db.gear_items.values())
    if studio_id is not None:
        gears = [g for g in gears if g["studio_id"] == studio_id]
    limit, offset = get_pagination()
    page, total = paginate(gears, limit, offset)
    return success_array(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

@bp.route("/studio/clients/register", methods=["POST"])
def register_client():
    # Open self-registration (PRD §2.1 / §3.1): callable without credentials.
    # Endpoint table authorizes Anonymous and StudioManager.
    principal = get_principal(open_endpoint=True)
    require_roles(principal, {"Anonymous", "StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    display_name = require_str(body, "display_name")
    email = require_str(body, "email")

    get_or_404(db.studios, studio_id, "studio")

    # Email uniqueness within studio (PRD §3.1).
    for c in db.clients.values():
        if c["studio_id"] == studio_id and c["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "email already registered in this studio")

    client = {
        "studio_id": studio_id,
        "display_name": display_name,
        "email": email,
        "wallet_credit_cents": 0,
    }
    stamp_common(client)
    db.clients[client["id"]] = client
    return success_object(public(client), status=201)


@bp.route("/studio/clients/<cid>", methods=["GET"])
def get_client(cid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    client = get_or_404(db.clients, cid, "client")
    # Ownership: a Client may only fetch their own record.
    if principal.role == "Client" and principal.user_id != cid:
        raise err("ERR_FORBIDDEN", "clients may only access their own record")
    return success_object(public(client))


@bp.route("/studio/clients", methods=["GET"])
def list_clients():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    from flask import request
    studio_id = request.args.get("studio_id")
    clients = list(db.clients.values())
    if studio_id is not None:
        clients = [c for c in clients if c["studio_id"] == studio_id]
    limit, offset = get_pagination()
    page, total = paginate(clients, limit, offset)
    return success_array(public_list(page), limit, offset, total)
