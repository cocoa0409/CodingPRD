"""CrewAssignment and SlotReservation routes."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, base_versioned, touch
from errors import ApiError
from middleware import require_role
from helpers import (
    get_body, require_str, require_enum, require_int, opt_str, get_pagination, paginate,
)
from response import success, list_success
from services import serializers as S
from services.lookups import (
    get_charter, get_captain, get_mate, get_crew_assignment, get_dock_slot,
    get_reservation,
)

bp = Blueprint("crew_and_slots", __name__)


def _sorted(collection):
    return sorted(collection.values(), key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# CrewAssignment
# ---------------------------------------------------------------------------
@bp.route("/crew-assignments", methods=["POST"])
def create_crew_assignment():
    require_role({"FleetManager"})
    body = get_body()
    # body FK fields + existence (priority 3, declared order: charter_id,
    # then captain_id/mate_id)
    charter_id = require_str(body, "charter_id")
    charter = get_charter(charter_id)
    role_slot = require_enum(body, "role_slot", {"CAPTAIN", "MATE"})
    captain_id = opt_str(body, "captain_id", default=None)
    mate_id = opt_str(body, "mate_id", default=None)
    captain = None
    mate = None
    if captain_id is not None:
        captain = get_captain(captain_id)
    if mate_id is not None:
        mate = get_mate(mate_id)

    trip_type = charter["trip_type"]
    boat = db.boats.get(charter["boat_id"])

    # --- cross-marina referential (priority 6) ---
    if captain is not None and captain["marina_id"] != charter["marina_id"]:
        raise ApiError("ERR_CROSS_MARINA_MISMATCH", "Captain marina differs from charter marina")
    if mate is not None and mate["marina_id"] != charter["marina_id"]:
        raise ApiError("ERR_CROSS_MARINA_MISMATCH", "Mate marina differs from charter marina")

    # --- credential/capacity safety (priority 7) ---
    if role_slot == "CAPTAIN" and captain is not None:
        # qualification: AVAILABLE + grade sufficient for trip
        if captain["status"] != "AVAILABLE":
            raise ApiError("ERR_CAPTAIN_UNQUALIFIED", "Captain is suspended")
        if trip_type == "OFFSHORE" and captain["uscg_license_grade"] == "OUPV":
            raise ApiError("ERR_CAPTAIN_UNQUALIFIED", "Captain grade insufficient for offshore")
        # boat offshore rated for OFFSHORE
        if trip_type == "OFFSHORE" and boat is not None and not boat["offshore_rated"]:
            raise ApiError("ERR_BOAT_NOT_OFFSHORE_RATED", "Boat not offshore rated")
        # license not lapsed for sail date (strictly after depart)
        if captain["_license_expires_dt"] <= charter["_depart_dt"]:
            raise ApiError("ERR_CREDENTIAL_EXPIRED_FOR_DATE", "Captain license lapsed for sail date")

    if role_slot == "MATE" and mate is not None:
        if trip_type == "OFFSHORE" and not mate["certified_offshore"]:
            raise ApiError("ERR_MATE_NOT_OFFSHORE_CERTIFIED", "Mate not offshore certified")
        if trip_type == "OFFSHORE" and boat is not None and not boat["offshore_rated"]:
            raise ApiError("ERR_BOAT_NOT_OFFSHORE_RATED", "Boat not offshore rated")

    # --- captain double-booking (priority 9): half-open overlap, no buffer ---
    if role_slot == "CAPTAIN" and captain is not None:
        new_start = charter["_depart_dt"]
        new_end = charter["_return_dt"]
        for a in db.crew_assignments.values():
            if a.get("captain_id") != captain_id:
                continue
            if a["status"] not in ("TENTATIVE", "LOCKED"):
                continue
            other = db.charters.get(a["charter_id"])
            if other is None:
                continue
            os, oe = other["_depart_dt"], other["_return_dt"]
            # strict half-open overlap: start < oe and os < end
            if new_start < oe and os < new_end:
                raise ApiError("ERR_CAPTAIN_DOUBLE_BOOKED", "Captain already booked in overlapping window")

    a = base_versioned()
    a.update({
        "charter_id": charter_id,
        "captain_id": captain_id,
        "mate_id": mate_id,
        "role_slot": role_slot,
        "status": "TENTATIVE",
        "_seq": db.next_seq(),
    })
    db.crew_assignments[a["id"]] = a
    return success(S.crew_assignment_out(a), status=201)


@bp.route("/crew-assignments", methods=["GET"])
def list_crew_assignments():
    require_role({"DockMaster", "FleetManager", "Captain"})
    limit, offset = get_pagination()
    items = _sorted(db.crew_assignments)
    for key in ("charter_id", "captain_id", "mate_id"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([S.crew_assignment_out(a) for a in page], limit, offset, total)


@bp.route("/crew-assignments/<assignment_id>", methods=["GET"])
def get_crew_assignment_route(assignment_id):
    require_role({"DockMaster", "FleetManager", "Captain"})
    a = get_crew_assignment(assignment_id)
    return success(S.crew_assignment_out(a), status=200)


# ---------------------------------------------------------------------------
# SlotReservation
# ---------------------------------------------------------------------------
def _window_conflict(slot_id, new_start, new_end, buffer_minutes):
    buf = timedelta(minutes=buffer_minutes)
    for r in db.slot_reservations.values():
        if r["dock_slot_id"] != slot_id:
            continue
        if r["status"] not in ("HELD", "OCCUPIED"):
            continue
        ex_start = r["_window_start_dt"]
        ex_end = r["_window_end_dt"]
        if new_start >= ex_end + buf:
            continue
        if new_end + buf <= ex_start:
            continue
        return True
    return False


@bp.route("/slot-reservations", methods=["POST"])
def create_slot_reservation():
    require_role({"DockMaster", "FleetManager"})
    body = get_body()
    # body FKs + existence (declared order: dock_slot_id, charter_id)
    dock_slot_id = require_str(body, "dock_slot_id")
    charter_id = require_str(body, "charter_id")
    slot = get_dock_slot(dock_slot_id)
    charter = get_charter(charter_id)
    expected_version = require_int(body, "expected_charter_version")

    # cross-marina referential (priority 6): slot.marina_id == charter.marina_id
    if slot["marina_id"] != charter["marina_id"]:
        raise ApiError("ERR_CROSS_MARINA_MISMATCH", "Slot marina differs from charter marina")

    boat = db.boats.get(charter["boat_id"])
    marina = db.marinas.get(charter["marina_id"])

    # safety (priority 7): slot length, slot active, marina open, decommission
    # PRD 3.3: marina must be OPEN, slot ACTIVE; length check is the 422 safety.
    if slot["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_SLOT_DECOMMISSIONED", "Dock slot is decommissioned")
    if marina is not None and marina["status"] != "OPEN":
        raise ApiError("ERR_MARINA_NOT_OPEN", "Marina is not open")
    if boat is not None and boat["length_ft"] > slot["max_boat_length_ft"]:
        raise ApiError("ERR_SLOT_LENGTH_EXCEEDED", "Boat length exceeds slot maximum")

    # temporal conflict (priority 8)
    new_start = charter["_depart_dt"]
    new_end = charter["_return_dt"]
    buffer_minutes = marina["turnaround_buffer_minutes"] if marina else 0
    if _window_conflict(dock_slot_id, new_start, new_end, buffer_minutes):
        raise ApiError("ERR_SLOT_WINDOW_CONFLICT", "Slot window conflicts with existing reservation")

    # OCC (priority 13)
    if expected_version != charter["version"]:
        raise ApiError("ERR_STALE_CHARTER_VERSION", "expected_charter_version is stale")

    r = base_versioned()
    r.update({
        "dock_slot_id": dock_slot_id,
        "charter_id": charter_id,
        "window_start": charter["depart_at"],
        "window_end": charter["return_at"],
        "status": "HELD",
        "_window_start_dt": new_start,
        "_window_end_dt": new_end,
        "_seq": db.next_seq(),
    })
    db.slot_reservations[r["id"]] = r
    # advance the charter's version (PRD 2.6: slot reservation creation bumps it)
    touch(charter)
    return success(S.slot_reservation_out(r), status=201)


@bp.route("/slot-reservations", methods=["GET"])
def list_slot_reservations():
    require_role({"DockMaster", "FleetManager"})
    limit, offset = get_pagination()
    items = _sorted(db.slot_reservations)
    for key in ("dock_slot_id", "charter_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([S.slot_reservation_out(r) for r in page], limit, offset, total)


@bp.route("/slot-reservations/<reservation_id>", methods=["GET"])
def get_slot_reservation_route(reservation_id):
    require_role({"DockMaster", "FleetManager"})
    r = get_reservation(reservation_id)
    return success(S.slot_reservation_out(r), status=200)
