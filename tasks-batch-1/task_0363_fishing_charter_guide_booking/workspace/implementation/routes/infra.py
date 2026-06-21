"""Routes for Marina, DockSlot, Boat, Captain, Mate, Permit, Customer, and the
test-driving clock."""
from flask import Blueprint

from db import db, base_versioned, base_id_only, touch
from errors import ApiError
from middleware import require_role
from helpers import (
    get_body, require_str, opt_str, require_int, opt_int, require_number,
    opt_bool, require_enum, opt_enum, require_dt, parse_dt, get_pagination, paginate,
)
from response import success, list_success
from services import serializers as S
from services.lookups import (
    get_marina, get_dock_slot, get_boat, get_captain, get_mate, get_permit,
    get_customer,
)

bp = Blueprint("infra", __name__)


def _sorted(collection):
    return sorted(collection.values(), key=lambda e: e["_seq"])


def _list(collection, out_fn, filters=None):
    limit, offset = get_pagination()
    items = _sorted(collection)
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [e for e in items if e.get(key) == val]
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([out_fn(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Marina
# ---------------------------------------------------------------------------
@bp.route("/marinas", methods=["POST"])
def create_marina():
    require_role({"DockMaster"})
    body = get_body()
    name = require_str(body, "name")
    slot_count = require_int(body, "slot_count", minimum=1)
    tz = opt_int(body, "timezone_offset_minutes", default=0)
    buf = opt_int(body, "turnaround_buffer_minutes", default=30, minimum=0)
    m = base_versioned()
    m.update({
        "name": name,
        "timezone_offset_minutes": tz,
        "slot_count": slot_count,
        "turnaround_buffer_minutes": buf,
        "status": "OPEN",
        "_seq": db.next_seq(),
    })
    db.marinas[m["id"]] = m
    return success(S.marina_out(m), status=201)


@bp.route("/marinas", methods=["GET"])
def list_marinas():
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    return _list(db.marinas, S.marina_out)


@bp.route("/marinas/<marina_id>", methods=["GET"])
def get_marina_route(marina_id):
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    m = get_marina(marina_id)
    return success(S.marina_out(m), status=200)


@bp.route("/marinas/<marina_id>/set-status", methods=["POST"])
def set_marina_status(marina_id):
    require_role({"DockMaster"})
    m = get_marina(marina_id)
    body = get_body()
    status = require_enum(body, "status", {"OPEN", "RESTRICTED", "CLOSED"})
    m["status"] = status
    touch(m)
    return success(S.marina_out(m), status=200)


# ---------------------------------------------------------------------------
# DockSlot
# ---------------------------------------------------------------------------
@bp.route("/dock-slots", methods=["POST"])
def create_dock_slot():
    require_role({"DockMaster"})
    body = get_body()
    marina_id = require_str(body, "marina_id")
    slot_label = require_str(body, "slot_label")
    max_len = require_number(body, "max_boat_length_ft", exclusive_min=0)
    get_marina(marina_id)
    s = base_versioned()
    s.update({
        "marina_id": marina_id,
        "slot_label": slot_label,
        "max_boat_length_ft": max_len,
        "status": "ACTIVE",
        "_seq": db.next_seq(),
    })
    db.dock_slots[s["id"]] = s
    return success(S.dock_slot_out(s), status=201)


@bp.route("/dock-slots", methods=["GET"])
def list_dock_slots():
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    from flask import request
    return _list(db.dock_slots, S.dock_slot_out,
                 {"marina_id": request.args.get("marina_id")})


@bp.route("/dock-slots/<slot_id>", methods=["GET"])
def get_dock_slot_route(slot_id):
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    s = get_dock_slot(slot_id)
    return success(S.dock_slot_out(s), status=200)


@bp.route("/dock-slots/<slot_id>/decommission", methods=["POST"])
def decommission_dock_slot(slot_id):
    require_role({"DockMaster"})
    s = get_dock_slot(slot_id)
    s["status"] = "DECOMMISSIONED"
    touch(s)
    return success(S.dock_slot_out(s), status=200)


# ---------------------------------------------------------------------------
# Boat
# ---------------------------------------------------------------------------
@bp.route("/boats", methods=["POST"])
def create_boat():
    require_role({"FleetManager"})
    body = get_body()
    marina_id = require_str(body, "marina_id")
    name = require_str(body, "name")
    length_ft = require_number(body, "length_ft", exclusive_min=0)
    passenger_capacity = require_int(body, "passenger_capacity", minimum=1)
    offshore_rated = opt_bool(body, "offshore_rated", default=False)
    get_marina(marina_id)
    b = base_versioned()
    b.update({
        "marina_id": marina_id,
        "name": name,
        "length_ft": length_ft,
        "passenger_capacity": passenger_capacity,
        "offshore_rated": offshore_rated,
        "status": "IN_SERVICE",
        "_seq": db.next_seq(),
    })
    db.boats[b["id"]] = b
    return success(S.boat_out(b), status=201)


@bp.route("/boats", methods=["GET"])
def list_boats():
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    from flask import request
    return _list(db.boats, S.boat_out, {"marina_id": request.args.get("marina_id")})


@bp.route("/boats/<boat_id>", methods=["GET"])
def get_boat_route(boat_id):
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    b = get_boat(boat_id)
    return success(S.boat_out(b), status=200)


@bp.route("/boats/<boat_id>/set-status", methods=["POST"])
def set_boat_status(boat_id):
    require_role({"FleetManager"})
    b = get_boat(boat_id)
    body = get_body()
    status = require_enum(body, "status", {"IN_SERVICE", "DRYDOCK"})
    b["status"] = status
    touch(b)
    return success(S.boat_out(b), status=200)


# ---------------------------------------------------------------------------
# Captain
# ---------------------------------------------------------------------------
@bp.route("/captains", methods=["POST"])
def create_captain():
    require_role({"FleetManager"})
    body = get_body()
    marina_id = require_str(body, "marina_id")
    full_name = require_str(body, "full_name")
    grade = require_enum(body, "uscg_license_grade", {"OUPV", "MASTER_50", "MASTER_100"})
    license_expires_on = require_dt(body, "license_expires_on")
    offshore_permit_id = opt_str(body, "offshore_permit_id", default=None)
    get_marina(marina_id)
    if offshore_permit_id is not None:
        get_permit(offshore_permit_id)
    c = base_versioned()
    c.update({
        "marina_id": marina_id,
        "full_name": full_name,
        "uscg_license_grade": grade,
        "license_expires_on": body["license_expires_on"],
        "offshore_permit_id": offshore_permit_id,
        "status": "AVAILABLE",
        "_license_expires_dt": license_expires_on,
        "_seq": db.next_seq(),
    })
    db.captains[c["id"]] = c
    return success(S.captain_out(c), status=201)


@bp.route("/captains", methods=["GET"])
def list_captains():
    require_role({"DockMaster", "FleetManager"})
    from flask import request
    return _list(db.captains, S.captain_out, {
        "marina_id": request.args.get("marina_id"),
        "offshore_permit_id": request.args.get("offshore_permit_id"),
    })


@bp.route("/captains/<captain_id>", methods=["GET"])
def get_captain_route(captain_id):
    require_role({"DockMaster", "FleetManager", "Captain"})
    c = get_captain(captain_id)
    return success(S.captain_out(c), status=200)


@bp.route("/captains/<captain_id>/set-status", methods=["POST"])
def set_captain_status(captain_id):
    require_role({"FleetManager"})
    c = get_captain(captain_id)
    body = get_body()
    status = require_enum(body, "status", {"AVAILABLE", "SUSPENDED"})
    c["status"] = status
    touch(c)
    return success(S.captain_out(c), status=200)


# ---------------------------------------------------------------------------
# Mate
# ---------------------------------------------------------------------------
@bp.route("/mates", methods=["POST"])
def create_mate():
    require_role({"FleetManager"})
    body = get_body()
    marina_id = require_str(body, "marina_id")
    full_name = require_str(body, "full_name")
    certified_offshore = opt_bool(body, "certified_offshore", default=False)
    get_marina(marina_id)
    m = base_versioned()
    m.update({
        "marina_id": marina_id,
        "full_name": full_name,
        "certified_offshore": certified_offshore,
        "status": "AVAILABLE",
        "_seq": db.next_seq(),
    })
    db.mates[m["id"]] = m
    return success(S.mate_out(m), status=201)


@bp.route("/mates", methods=["GET"])
def list_mates():
    require_role({"DockMaster", "FleetManager"})
    from flask import request
    return _list(db.mates, S.mate_out, {"marina_id": request.args.get("marina_id")})


@bp.route("/mates/<mate_id>", methods=["GET"])
def get_mate_route(mate_id):
    require_role({"DockMaster", "FleetManager", "Captain"})
    m = get_mate(mate_id)
    return success(S.mate_out(m), status=200)


# ---------------------------------------------------------------------------
# Permit (immutable: id + created_at only)
# ---------------------------------------------------------------------------
@bp.route("/permits", methods=["POST"])
def create_permit():
    require_role({"FleetManager"})
    body = get_body()
    permit_kind = require_enum(body, "permit_kind", {"FEDERAL_OFFSHORE", "STATE_INSHORE"})
    permit_number = require_str(body, "permit_number")
    valid_through = require_dt(body, "valid_through")
    daily_bag_limit = require_int(body, "daily_bag_limit", minimum=0)
    p = base_id_only()
    p.update({
        "permit_kind": permit_kind,
        "permit_number": permit_number,
        "valid_through": body["valid_through"],
        "daily_bag_limit": daily_bag_limit,
        "_valid_through_dt": valid_through,
        "_seq": db.next_seq(),
    })
    db.permits[p["id"]] = p
    return success(S.permit_out(p), status=201)


@bp.route("/permits/<permit_id>", methods=["GET"])
def get_permit_route(permit_id):
    require_role({"DockMaster", "FleetManager", "Captain"})
    p = get_permit(permit_id)
    return success(S.permit_out(p), status=200)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
def create_customer():
    require_role({"DockMaster", "FleetManager", "Customer"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    loyalty_tier = opt_enum(body, "loyalty_tier", {"STANDARD", "SILVER", "GOLD"},
                            default="STANDARD")
    c = base_versioned()
    c.update({
        "full_name": full_name,
        "email": email,
        "loyalty_tier": loyalty_tier,
        "_seq": db.next_seq(),
    })
    db.customers[c["id"]] = c
    return success(S.customer_out(c), status=201)


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer_route(customer_id):
    require_role({"DockMaster", "FleetManager", "Customer"})
    c = get_customer(customer_id)
    return success(S.customer_out(c), status=200)


# ---------------------------------------------------------------------------
# Test-driving clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role({"DockMaster", "FleetManager"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_dt(to_iso, "to_iso8601")
    db.set_clock(dt)
    return success({}, status=200)
