"""Booking lifecycle, overlap geometry, and reconciliation service.

Implements the Booking state machine (SCAFFOLD section 1.2) and the temporal
overlap calculations (room: half-open, staff: closed) from PRD sections 3.6-3.10.
"""

from datetime import timedelta

from db import db
from errors import err
from services import calc
from services.common import iso_from_dt, parse_iso8601, touch


# ----------------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------------

def clock_now():
    return parse_iso8601(db.clock["current_utc"], "current_utc")


# ----------------------------------------------------------------------------
# Existence helpers (priority 3/4)
# ----------------------------------------------------------------------------

def get_booking_or_404(booking_id):
    b = db.bookings.get(booking_id)
    if b is None:
        raise err("ERR_BOOKING_NOT_FOUND", "Booking %s not found" % booking_id)
    return b


# ----------------------------------------------------------------------------
# Room window overlap (calc room_window_occupancy) — half-open intervals
# ----------------------------------------------------------------------------

ACTIVE_BOOKING_STATES = {"HELD", "CONFIRMED", "WEATHER_HOLD", "RESCHEDULED"}


def _candidate_window_for(booking, start_override=None):
    """Return (start, buffered_end) for a candidate window, optionally overriding
    the start (used for reschedule which prices the NEW start)."""
    room = db.rooms[booking["room_id"]]
    if start_override is not None:
        start = start_override
    else:
        start = parse_iso8601(booking["event_start_utc"], "event_start_utc")
    end = start + timedelta(minutes=booking["effective_duration_minutes"])
    buffered_end = end + timedelta(minutes=room["buffer_minutes"])
    return start, buffered_end


def check_room_overlap(booking, start_override=None):
    """Raise ERR_ROOM_WINDOW_CONFLICT if the candidate window collides with any
    other active booking on the same room. Half-open: adjacency is NOT a conflict.

    conflict := (a.start < b.end_with_buffer) AND (b.start < a.end_with_buffer)
    """
    a_start, a_end = _candidate_window_for(booking, start_override)
    for other in db.bookings.values():
        if other["id"] == booking["id"]:
            continue
        if other["room_id"] != booking["room_id"]:
            continue
        if other["status"] not in ACTIVE_BOOKING_STATES:
            continue
        b_start, b_end = calc.booking_room_interval(other)
        if a_start < b_end and b_start < a_end:
            raise err("ERR_ROOM_WINDOW_CONFLICT",
                      "Requested room window overlaps another booking")


# ----------------------------------------------------------------------------
# Staff window overlap (calc staff_window_occupancy) — closed intervals
# ----------------------------------------------------------------------------

def staff_occupancy_interval(booking):
    """Closed staff interval [start, event_end + buffer], inclusive of buffer."""
    room = db.rooms[booking["room_id"]]
    start = parse_iso8601(booking["event_start_utc"], "event_start_utc")
    end = parse_iso8601(booking["event_end_utc"], "event_end_utc")
    end_incl = end + timedelta(minutes=room["buffer_minutes"])
    return start, end_incl


def check_staff_overlap(staff_member_id, booking):
    """Raise ERR_STAFF_WINDOW_CONFLICT if this staff member's closed window for the
    candidate booking touches any other ASSIGNED assignment's window.

    conflict := (a.start <= b.end_incl) AND (b.start <= a.end_incl)  (closed)
    Candidate set: other ASSIGNED assignments for this staff member whose parent
    booking is in {HELD, CONFIRMED, WEATHER_HOLD, RESCHEDULED}.
    """
    a_start, a_end = staff_occupancy_interval(booking)
    for asg in db.staff_assignments.values():
        if asg["staff_member_id"] != staff_member_id:
            continue
        if asg["status"] != "ASSIGNED":
            continue
        parent = db.bookings.get(asg["booking_id"])
        if parent is None or parent["status"] not in ACTIVE_BOOKING_STATES:
            continue
        if parent["id"] == booking["id"]:
            # Same booking — would only happen for a different role; still a real
            # double-booking of the same person on the same window. Treat as conflict.
            pass
        b_start, b_end = staff_occupancy_interval(parent)
        if a_start <= b_end and b_start <= a_end:
            raise err("ERR_STAFF_WINDOW_CONFLICT",
                      "Staff member window overlaps another assignment")


# ----------------------------------------------------------------------------
# Confirm staffing completeness (priority 9)
# ----------------------------------------------------------------------------

SKILL_FOR_KIND = {"CHARACTER": "ENTERTAINER", "CAKE": "COOK", "EXTRA_TIME": "NONE"}


def assigned_hosts(booking_id):
    return [a for a in db.staff_assignments.values()
            if a["booking_id"] == booking_id and a["status"] == "ASSIGNED"
            and a["role_on_event"] == "HOST"]


def assigned_roles(booking_id):
    return {a["role_on_event"] for a in db.staff_assignments.values()
            if a["booking_id"] == booking_id and a["status"] == "ASSIGNED"}


def check_staffing_complete(booking):
    hosts = assigned_hosts(booking["id"])
    if len(hosts) != 1:
        raise err("ERR_HOST_NOT_ASSIGNED",
                  "Exactly one ASSIGNED HOST is required to confirm")
    roles = assigned_roles(booking["id"])
    for a in calc.active_add_ons(booking["id"]):
        needed = SKILL_FOR_KIND.get(a["kind"], "NONE")
        if needed != "NONE" and needed not in roles:
            raise err("ERR_ADDON_STAFF_MISSING",
                      "Add-on %s requires an ASSIGNED %s" % (a["kind"], needed))


# ----------------------------------------------------------------------------
# Cascades
# ----------------------------------------------------------------------------

def release_all_staff(booking_id):
    for a in db.staff_assignments.values():
        if a["booking_id"] == booking_id and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            touch(a)


def cascade_cancel(booking):
    """On cancel: ACTIVE add-ons -> REMOVED, ASSIGNED staff -> RELEASED,
    DRAFT/SIGNED waivers -> VOIDED."""
    for a in db.add_ons.values():
        if a["booking_id"] == booking["id"] and a["status"] == "ACTIVE":
            a["status"] = "REMOVED"
            touch(a)
    for asg in db.staff_assignments.values():
        if asg["booking_id"] == booking["id"] and asg["status"] == "ASSIGNED":
            asg["status"] = "RELEASED"
            touch(asg)
    for w in db.waivers.values():
        if w["booking_id"] == booking["id"] and w["status"] in ("DRAFT", "SIGNED"):
            w["status"] = "VOIDED"
            touch(w)


# ----------------------------------------------------------------------------
# Tiered cancellation refund (calc cancellation_refund)
# ----------------------------------------------------------------------------

FREE_CANCEL_HOURS = 72


def cancellation_refund_amount(booking, prior_status):
    """Compute the synthesized refund magnitude. prior_status is the booking's
    status BEFORE the cancel (used to detect pre-confirmation)."""
    amount_paid = booking["amount_paid_cents"]
    start = parse_iso8601(booking["event_start_utc"], "event_start_utc")
    hours_to_event = (start - clock_now()).total_seconds() / 3600.0
    if prior_status in ("QUOTE_DRAFT", "HELD"):
        return amount_paid
    if hours_to_event >= FREE_CANCEL_HOURS:
        return amount_paid
    if hours_to_event >= 0:
        return max(0, amount_paid - booking["deposit_due_cents"])
    return 0
