"""Charge ledger, overlap predicates, occupancy counting, cancellation cascade."""

import db
from services import settlement

BLOCKING_BOOKING_STATES = ("CONFIRMED", "CHECKED_OUT", "INTERRUPTED", "RETURNED")
ACTIVE_WINDOW_STATES = ("SCHEDULED", "IN_PROGRESS")


# ---------------------------------------------------------------------------
# Charge ledger
# ---------------------------------------------------------------------------

def post_charge(booking_id, line_type, amount_cents, status, note=None):
    """Post a ledger line. Zero-amount lines are never posted."""
    if amount_cents == 0:
        return None
    rec = db.base_record()
    rec.update({
        "booking_id": booking_id,
        "line_type": line_type,
        "amount_cents": amount_cents,
        "status": status,
        "note": note,
    })
    return db.insert("charges", rec)


def charges_of(booking_id):
    return [c for c in db.all_of("charges") if c["booking_id"] == booking_id]


# ---------------------------------------------------------------------------
# Interval predicates
# ---------------------------------------------------------------------------

def booking_overlap_exists(vessel_id, start_date, end_date, exclude_booking_id=None):
    """Half-open overlap: [start, end) vs same-vessel bookings in the
    blocking set. Pure adjacency (end == start) is allowed."""
    for b in db.all_of("bookings"):
        if b["vessel_id"] != vessel_id:
            continue
        if b["id"] == exclude_booking_id:
            continue
        if b["status"] not in BLOCKING_BOOKING_STATES:
            continue
        if start_date < b["end_date"] and b["start_date"] < end_date:
            return True
    return False


def maintenance_conflict_exists(vessel_id, start_date, end_date):
    """Closed-interval conflict with any SCHEDULED/IN_PROGRESS window of the
    vessel: window.start <= end_date AND window.end >= start_date (touching
    endpoints count as conflict)."""
    for w in db.all_of("maintenance_windows"):
        if w["vessel_id"] != vessel_id:
            continue
        if w["status"] not in ACTIVE_WINDOW_STATES:
            continue
        if w["start_date"] <= end_date and w["end_date"] >= start_date:
            return True
    return False


def window_conflict_with_blocking_bookings(vessel_id, start_date, end_date):
    """Closed-interval window-vs-booking comparison for window creation:
    window.start_date <= booking.end_date AND window.end_date >= booking.start_date."""
    for b in db.all_of("bookings"):
        if b["vessel_id"] != vessel_id:
            continue
        if b["status"] not in BLOCKING_BOOKING_STATES:
            continue
        if start_date <= b["end_date"] and end_date >= b["start_date"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Zone-night occupancy (scaffold §1.3 zone_night_occupancy)
# ---------------------------------------------------------------------------

def zone_night_occupancy(zone_id, night_date, exclude_booking_id=None):
    """Count APPROVED itineraries whose bookings are in the blocking set and
    which carry a waypoint on (zone_id, night_date). SUPERSEDED/VOID never
    count. The submitting booking is excluded (its prior APPROVED itinerary
    is superseded before counting)."""
    count = 0
    for it in db.all_of("itineraries"):
        if it["status"] != "APPROVED":
            continue
        if exclude_booking_id is not None and it["booking_id"] == exclude_booking_id:
            continue
        booking = db.get("bookings", it["booking_id"])
        if booking is None or booking["status"] not in BLOCKING_BOOKING_STATES:
            continue
        for w in it["waypoints"]:
            if w["zone_id"] == zone_id and w["night_date"] == night_date:
                count += 1
                break
    return count


# ---------------------------------------------------------------------------
# Cancellation cascade (renter-initiated and system)
# ---------------------------------------------------------------------------

def cancel_booking(booking, reason, system):
    """Drive HELD/CONFIRMED -> CANCELLED with the full side-effect set.

    reason: RENTER_REQUEST | WEATHER | RENTER_SUSPENDED | VESSEL_MECHANICAL.
    system=True forces the 100% refund path for CONFIRMED bookings.
    For renter-initiated cancels the WEATHER stamp is applied only when the
    weather variant actually applied; otherwise RENTER_REQUEST is recorded.
    """
    pct, applied_weather = settlement.cancellation_refund_pct(
        booking, system_reason=reason if system else None
    )
    if not system:
        reason = "WEATHER" if applied_weather else "RENTER_REQUEST"

    refund_cents = settlement.cancellation_refund_cents(
        booking["quoted_total_cents"], pct
    ) if booking["status"] == "CONFIRMED" else 0

    if booking["status"] == "CONFIRMED" and refund_cents > 0:
        post_charge(
            booking["id"],
            "CANCELLATION_REFUND",
            -refund_cents,
            "REFUNDED",
            note=reason,
        )
        booking["refund_issued_cents"] += refund_cents

    booking["cancellation_reason"] = reason
    booking["deposit_status"] = "RELEASED"
    booking["deposit_released_cents"] = booking["deposit_held_cents"]
    booking["deposit_applied_cents"] = 0

    for t in db.all_of("cleaning_turns"):
        if t["booking_id"] == booking["id"] and t["status"] in ("SCHEDULED", "IN_PROGRESS"):
            t["status"] = "CANCELLED"
            db.touch(t)

    if booking["orientation_status"] in ("IN_PROGRESS", "COMPLETED", "COUNTERSIGNED"):
        booking["orientation_status"] = "CANCELLED"

    for it in db.all_of("itineraries"):
        if it["booking_id"] == booking["id"] and it["status"] == "APPROVED":
            it["status"] = "VOID"
            db.touch(it)

    booking["status"] = "CANCELLED"
    db.touch(booking)
