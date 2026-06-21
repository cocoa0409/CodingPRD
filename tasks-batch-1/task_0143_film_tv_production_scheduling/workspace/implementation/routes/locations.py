"""Locations and permits — window-conflict guarded approval, branching lifecycle."""
from flask import Blueprint, request

from db import db, now_iso, new_id
from errors import err
from middleware import authenticate, authorize
from helpers import (get_json_body, require_string, parse_pagination, paginate,
                     parse_iso_datetime)
from response import success_object, success_array
from services.serialize import public
from services.recompute import touch

bp = Blueprint("locations", __name__)

ALL_READ = {"LineProducer", "FirstAD", "UnionRep"}


# --- Location ---------------------------------------------------------------
@bp.route("/locations", methods=["POST"])
def create_location():
    role = authenticate()
    authorize(role, {"LineProducer"})
    body = get_json_body()
    production_id = require_string(body, "production_id")
    if production_id not in db.productions:
        raise err("ERR_NOT_FOUND", "Production not found.")
    name = require_string(body, "name")
    address = require_string(body, "address")
    with db.lock:
        ts = now_iso()
        loc = {
            "id": new_id(),
            "production_id": production_id,
            "name": name,
            "address": address,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.locations[loc["id"]] = loc
        return success_object(public(loc), status=201)


@bp.route("/locations/<lid>", methods=["GET"])
def get_location(lid):
    role = authenticate()
    authorize(role, ALL_READ)
    loc = db.locations.get(lid)
    if not loc:
        raise err("ERR_NOT_FOUND", "Location not found.")
    return success_object(public(loc))


@bp.route("/locations", methods=["GET"])
def list_locations():
    role = authenticate()
    authorize(role, ALL_READ)
    limit, offset = parse_pagination()
    production_id = request.args.get("production_id")
    items = list(db.locations.values())
    if production_id is not None:
        items = [l for l in items if l["production_id"] == production_id]
    page, total = paginate(items, limit, offset)
    return success_array([public(l) for l in page], limit, offset, total)


# --- LocationPermit ---------------------------------------------------------
@bp.route("/location-permits", methods=["POST"])
def create_permit():
    role = authenticate()
    authorize(role, {"LineProducer"})
    body = get_json_body()
    location_id = require_string(body, "location_id")
    if location_id not in db.locations:
        raise err("ERR_NOT_FOUND", "Location not found.")
    permit_number = require_string(body, "permit_number")
    window_start_str = require_string(body, "window_start")
    window_end_str = require_string(body, "window_end")
    ws = parse_iso_datetime(window_start_str, "window_start")
    we = parse_iso_datetime(window_end_str, "window_end")
    # ERR_INVALID_TIME_RANGE (priority 13): window_end strictly after window_start
    if not (we > ws):
        raise err("ERR_INVALID_TIME_RANGE", "window_end must be strictly after window_start.")
    with db.lock:
        ts = now_iso()
        permit = {
            "id": new_id(),
            "location_id": location_id,
            "permit_number": permit_number,
            "window_start": window_start_str,
            "window_end": window_end_str,
            "status": "REQUESTED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.location_permits[permit["id"]] = permit
        return success_object(public(permit), status=201)


@bp.route("/location-permits/<pid>", methods=["GET"])
def get_permit(pid):
    role = authenticate()
    authorize(role, ALL_READ)
    permit = db.location_permits.get(pid)
    if not permit:
        raise err("ERR_NOT_FOUND", "Permit not found.")
    return success_object(public(permit))


@bp.route("/location-permits", methods=["GET"])
def list_permits():
    role = authenticate()
    authorize(role, ALL_READ)
    limit, offset = parse_pagination()
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    items = list(db.location_permits.values())
    if location_id is not None:
        items = [p for p in items if p["location_id"] == location_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_array([public(p) for p in page], limit, offset, total)


@bp.route("/location-permits/<pid>/approve", methods=["POST"])
def approve_permit(pid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    with db.lock:
        permit = db.location_permits.get(pid)
        if not permit:
            raise err("ERR_NOT_FOUND", "Permit not found.")
        if permit["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Permit must be REQUESTED to approve.")
        # ERR_PERMIT_WINDOW_CONFLICT (priority 10): half-open [start, end) overlap
        # with another APPROVED/ACTIVE permit on the same location.
        ws = parse_iso_datetime(permit["window_start"], "window_start")
        we = parse_iso_datetime(permit["window_end"], "window_end")
        for other in db.location_permits.values():
            if other["id"] == permit["id"]:
                continue
            if other["location_id"] != permit["location_id"]:
                continue
            if other["status"] not in ("APPROVED", "ACTIVE"):
                continue
            o_ws = parse_iso_datetime(other["window_start"], "window_start")
            o_we = parse_iso_datetime(other["window_end"], "window_end")
            # half-open overlap: start < o_end AND o_start < end (abutting = no conflict)
            if ws < o_we and o_ws < we:
                raise err("ERR_PERMIT_WINDOW_CONFLICT",
                          "Permit window overlaps an existing APPROVED/ACTIVE permit.")
        permit["status"] = "APPROVED"
        touch(permit)
        return success_object(public(permit))


def _simple_transition(pid, from_states, to_state):
    permit = db.location_permits.get(pid)
    if not permit:
        raise err("ERR_NOT_FOUND", "Permit not found.")
    if permit["status"] not in from_states:
        raise err("ERR_INVALID_STATE",
                  f"Permit must be in {sorted(from_states)} for this transition.")
    permit["status"] = to_state
    touch(permit)
    return permit


@bp.route("/location-permits/<pid>/deny", methods=["POST"])
def deny_permit(pid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    with db.lock:
        return success_object(public(_simple_transition(pid, {"REQUESTED"}, "DENIED")))


@bp.route("/location-permits/<pid>/activate", methods=["POST"])
def activate_permit(pid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    with db.lock:
        return success_object(public(_simple_transition(pid, {"APPROVED"}, "ACTIVE")))


@bp.route("/location-permits/<pid>/expire", methods=["POST"])
def expire_permit(pid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    with db.lock:
        return success_object(public(_simple_transition(pid, {"ACTIVE"}, "EXPIRED")))


@bp.route("/location-permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    with db.lock:
        return success_object(public(_simple_transition(pid, {"APPROVED", "ACTIVE"}, "REVOKED")))
