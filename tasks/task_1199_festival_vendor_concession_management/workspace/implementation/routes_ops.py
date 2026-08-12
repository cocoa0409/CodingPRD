"""Load-in slots and vehicle reservations."""
from datetime import timedelta

from flask import Blueprint

import serialize
from calc import SLOT_LOCK_MINUTES, CHECKIN_GRACE_MINUTES, slot_reserved
from store import db
from util import (body_json, err, get_or_404, list_response, new_id, req_int,
                  req_str, req_enum, parse_dt, require_role, stamp_new,
                  success, touch)

bp = Blueprint("ops", __name__)

GATES = ("GATE_A", "GATE_B", "GATE_C")
SLOT_READ_ROLES = ("FestivalDirector", "VendorManager", "OperationsLead",
                   "FinanceLead", "Vendor")


# ---------------------------------------------------------------------------
# Load-in slots
# ---------------------------------------------------------------------------

@bp.route("/load-in-slots", methods=["POST"])
def create_slot():
    require_role("OperationsLead")
    b = body_json()
    festival = None
    if b.get("festival_id") is not None:
        festival = get_or_404(db.festivals, b.get("festival_id"),
                              "ERR_FESTIVAL_NOT_FOUND", "Festival")
    gate = req_enum(b, "gate", GATES)
    window_start = parse_dt(b.get("window_start"), "window_start")
    window_end = parse_dt(b.get("window_end"), "window_end")
    max_vehicles = req_int(b, "max_vehicles", min_v=1)
    if festival is None:
        get_or_404(db.festivals, b.get("festival_id"), "ERR_FESTIVAL_NOT_FOUND", "Festival")
    # (11) Temporal validity of the window.
    if not window_end > window_start:
        err("ERR_INVALID_WINDOW", 400, "window_end must be strictly after window_start")
    slot = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "festival_id": festival["id"],
        "gate": gate,
        "window_start": window_start,
        "window_end": window_end,
        "max_vehicles": max_vehicles,
    })
    db.slots[slot["id"]] = slot
    return success(serialize.serialize_slot(slot), 201)


@bp.route("/load-in-slots", methods=["GET"])
def list_slots():
    require_role(*SLOT_READ_ROLES)
    return list_response(list(db.slots.values()), serialize.serialize_slot,
                         {"festival_id": "festival_id", "gate": "gate"})


@bp.route("/load-in-slots/<slotId>", methods=["GET"])
def get_slot(slotId):
    require_role(*SLOT_READ_ROLES)
    slot = get_or_404(db.slots, slotId, "ERR_SLOT_NOT_FOUND", "Load-in slot")
    return success(serialize.serialize_slot(slot))


# ---------------------------------------------------------------------------
# Load-in reservations
# ---------------------------------------------------------------------------

def _vendor_of_assignment(assignment):
    return db.applications[assignment["application_id"]]["vendor_id"]


@bp.route("/load-in-reservations", methods=["POST"])
def create_reservation():
    uid, role = require_role("OperationsLead", "Vendor")
    b = body_json()
    # (4) Body FK existence.
    assignment = None
    if b.get("assignment_id") is not None:
        assignment = get_or_404(db.assignments, b.get("assignment_id"),
                                "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    slot = None
    if b.get("slot_id") is not None:
        slot = get_or_404(db.slots, b.get("slot_id"),
                          "ERR_SLOT_NOT_FOUND", "Load-in slot")

    # (5) Entity-backed ownership for Vendor actors.
    if role == "Vendor" and assignment is not None:
        if _vendor_of_assignment(assignment) != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "A vendor may only book reservations for its own assignments")

    # (8) Request shape.
    vehicle_count = req_int(b, "vehicle_count", min_v=1)
    if assignment is None:
        get_or_404(db.assignments, b.get("assignment_id"),
                   "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    if slot is None:
        get_or_404(db.slots, b.get("slot_id"), "ERR_SLOT_NOT_FOUND", "Load-in slot")

    # (9) Cross-festival integrity.
    if slot["festival_id"] != assignment["festival_id"]:
        err("ERR_CROSS_FESTIVAL_REFERENCE", 409,
            "Slot and assignment belong to different festivals")

    # (11) Slot lock horizon: booking locks at window_start - 120 minutes.
    if not db.clock < slot["window_start"] - timedelta(minutes=SLOT_LOCK_MINUTES):
        err("ERR_SLOT_LOCKED", 409,
            "The slot is locked within 120 minutes of window_start")

    # (12) Capacity (inclusive boundary) and same-assignment window overlap.
    if slot_reserved(slot["id"]) + vehicle_count > slot["max_vehicles"]:
        err("ERR_SLOT_CAPACITY_EXCEEDED", 409,
            "Slot vehicle capacity would be exceeded")
    for other in db.reservations.values():
        if other["assignment_id"] != assignment["id"]:
            continue
        if other["status"] not in ("BOOKED", "CHECKED_IN", "COMPLETED"):
            continue
        other_slot = db.slots[other["slot_id"]]
        if (other_slot["window_start"] < slot["window_end"]
                and slot["window_start"] < other_slot["window_end"]):
            err("ERR_VEHICLE_WINDOW_OVERLAP", 409,
                "Reservation windows overlap for this assignment")

    reservation = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "assignment_id": assignment["id"],
        "slot_id": slot["id"],
        "festival_id": slot["festival_id"],
        "vehicle_count": vehicle_count,
        "status": "BOOKED",
        "checked_in_at": None,
    })
    db.reservations[reservation["id"]] = reservation
    return success(serialize.serialize_reservation(reservation), 201)


@bp.route("/load-in-reservations", methods=["GET"])
def list_reservations():
    require_role(*SLOT_READ_ROLES)
    return list_response(list(db.reservations.values()),
                         serialize.serialize_reservation, {
                             "assignment_id": "assignment_id",
                             "slot_id": "slot_id",
                             "festival_id": "festival_id",
                             "status": "status",
                         })


@bp.route("/load-in-reservations/<reservationId>", methods=["GET"])
def get_reservation(reservationId):
    require_role(*SLOT_READ_ROLES)
    reservation = get_or_404(db.reservations, reservationId,
                             "ERR_RESERVATION_NOT_FOUND", "Reservation")
    return success(serialize.serialize_reservation(reservation))


@bp.route("/load-in-reservations/<reservationId>/check-in", methods=["POST"])
def check_in_reservation(reservationId):
    require_role("OperationsLead")
    reservation = get_or_404(db.reservations, reservationId,
                             "ERR_RESERVATION_NOT_FOUND", "Reservation")
    if reservation["status"] != "BOOKED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"check-in is not permitted from {reservation['status']}")
    slot = db.slots[reservation["slot_id"]]
    grace_end = slot["window_end"] + timedelta(minutes=CHECKIN_GRACE_MINUTES)
    if not (slot["window_start"] <= db.clock <= grace_end):
        err("ERR_CHECKIN_WINDOW_CLOSED", 409,
            "Check-in is only allowed inside [window_start, window_end + 30min]")
    reservation["status"] = "CHECKED_IN"
    reservation["checked_in_at"] = db.clock
    touch(reservation)
    return success(serialize.serialize_reservation(reservation))


@bp.route("/load-in-reservations/<reservationId>/cancel", methods=["POST"])
def cancel_reservation(reservationId):
    uid, role = require_role("OperationsLead", "Vendor")
    reservation = get_or_404(db.reservations, reservationId,
                             "ERR_RESERVATION_NOT_FOUND", "Reservation")
    if role == "Vendor":
        assignment = db.assignments[reservation["assignment_id"]]
        if _vendor_of_assignment(assignment) != uid:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "A vendor may only cancel its own reservations")
    if reservation["status"] != "BOOKED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"cancel is not permitted from {reservation['status']}")
    slot = db.slots[reservation["slot_id"]]
    if not db.clock < slot["window_start"] - timedelta(minutes=SLOT_LOCK_MINUTES):
        err("ERR_SLOT_LOCKED", 409,
            "The slot is locked within 120 minutes of window_start")
    reservation["status"] = "CANCELLED"
    touch(reservation)
    return success(serialize.serialize_reservation(reservation))
