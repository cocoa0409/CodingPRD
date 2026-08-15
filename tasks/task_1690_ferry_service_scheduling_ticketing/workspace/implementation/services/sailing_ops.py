"""Sailing lifecycle operations: cancellation cascade, departure sweeps,
completion, and vessel out-of-service cascade (PRD §3.7, §3.8, §3.1)."""

from db import db
from services.calculations import (
    touch, recompute_sailing_counters, crew_manning_compliance,
    standby_clearance_sweep,
)

# Booking statuses cancelled by the operator cascade (PRD §3.8 hop 1)
CASCADE_CANCEL_BOOKING_STATUSES = ("RESERVED", "CONFIRMED", "MODIFIED", "CHECKED_IN")


def release_assignment(assignment):
    """CrewAssignment ASSIGNED -> RELEASED with member status sweep."""
    if assignment["status"] != "ASSIGNED":
        return
    assignment["status"] = "RELEASED"
    touch(assignment)
    _sweep_member_status(assignment["crew_member_id"])


def _sweep_member_status(crew_member_id):
    """CrewMember with no remaining ASSIGNED assignments -> AVAILABLE."""
    member = db.crew_members.get(crew_member_id)
    if member is None:
        return
    remaining = any(
        a["crew_member_id"] == crew_member_id and a["status"] == "ASSIGNED"
        for a in db.crew_assignments.values()
    )
    if not remaining and member["status"] == "ASSIGNED":
        member["status"] = "AVAILABLE"
        touch(member)


def cancel_sailing_cascade(sailing, cancel_reason):
    """Three-hop cascade (PRD §3.8):
    hop 1: bookings {RESERVED, CONFIRMED, MODIFIED, CHECKED_IN} -> CANCELLED,
           refund credit += final_fare_cents for settled bookings.
    hop 2: standby entries {WAITING, CALLED} -> EXPIRED (CLEARED stay CLEARED).
    hop 3: crew assignments ASSIGNED -> RELEASED; member sweep.
    """
    sid = sailing["id"]

    # Hop 1 — bookings
    for b in list(db.bookings.values()):
        if b["sailing_id"] != sid:
            continue
        if b["status"] in CASCADE_CANCEL_BOOKING_STATUSES:
            was_settled = b["status"] in ("CONFIRMED", "MODIFIED", "CHECKED_IN")
            b["status"] = "CANCELLED"
            touch(b)
            if was_settled and b.get("final_fare_cents") is not None:
                customer = db.customers.get(b["customer_id"])
                if customer is not None:
                    customer["refund_credit_cents"] = int(customer.get("refund_credit_cents", 0)) + int(b["final_fare_cents"])
                    touch(customer)

    # Hop 2 — standby entries
    for e in list(db.standby_entries.values()):
        if e["sailing_id"] == sid and e["status"] in ("WAITING", "CALLED"):
            e["status"] = "EXPIRED"
            touch(e)

    # Hop 3 — crew assignments
    for a in list(db.crew_assignments.values()):
        if a["sailing_id"] == sid and a["status"] == "ASSIGNED":
            release_assignment(a)

    sailing["status"] = "CANCELLED"
    sailing["cancel_reason"] = cancel_reason
    recompute_sailing_counters(sailing)
    touch(sailing)


def depart_sailing(sailing):
    """BOARDING -> DEPARTED (PRD §3.7):
    - bookings CONFIRMED/MODIFIED never checked in -> NO_SHOW (fare forfeited)
    - standby WAITING/CALLED -> NO_BOARD
    """
    sid = sailing["id"]
    for b in list(db.bookings.values()):
        if b["sailing_id"] == sid and b["status"] in ("CONFIRMED", "MODIFIED"):
            b["status"] = "NO_SHOW"
            touch(b)
    for e in list(db.standby_entries.values()):
        if e["sailing_id"] == sid and e["status"] in ("WAITING", "CALLED"):
            e["status"] = "NO_BOARD"
            touch(e)
    sailing["status"] = "DEPARTED"
    recompute_sailing_counters(sailing)
    touch(sailing)


def complete_sailing(sailing):
    """DEPARTED -> COMPLETED: BOARDED bookings -> COMPLETED; crew released."""
    sid = sailing["id"]
    for b in list(db.bookings.values()):
        if b["sailing_id"] == sid and b["status"] == "BOARDED":
            b["status"] = "COMPLETED"
            touch(b)
    for a in list(db.crew_assignments.values()):
        if a["sailing_id"] == sid and a["status"] == "ASSIGNED":
            release_assignment(a)
    sailing["status"] = "COMPLETED"
    recompute_sailing_counters(sailing)
    touch(sailing)


def begin_boarding_sailing(sailing):
    """BOOKING_CLOSED -> BOARDING: run standby clearance sweep (PRD §3.7)."""
    sailing["status"] = "BOARDING"
    standby_clearance_sweep(sailing)
    touch(sailing)


def vessel_out_of_service_cascade(vessel):
    """Vessel -> OUT_OF_SERVICE cancels its still-SCHEDULED sailings with
    cancel_reason=MECHANICAL, firing the full cancellation cascade (§3.1)."""
    vessel["status"] = "OUT_OF_SERVICE"
    touch(vessel)
    for s in list(db.sailings.values()):
        if s["vessel_id"] == vessel["id"] and s["status"] == "SCHEDULED":
            cancel_sailing_cascade(s, "MECHANICAL")
