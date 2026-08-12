"""Cascades, refund waterfall, and derived-field recomputation (PRD §3)."""
from datetime import timedelta
from decimal import Decimal

from db import store
from util import bump, new_immutable, now
from services.pricing import (
    COMPLIANCE_PENALTY_RATE,
    DAILY_CAPACITY_MINUTES,
    TERMINAL_BOOKING_STATES,
    rhu,
)


def booking_duration_minutes(booking):
    return int((booking["end_time"] - booking["start_time"]).total_seconds() // 60)


def recompute_handler_minutes(handler_id):
    """scheduled_minutes_total = sum of event durations over ASSIGNED assignments."""
    total = 0
    for sa in store.staff_assignments.values():
        if sa["handler_id"] == handler_id and sa["status"] == "ASSIGNED":
            total += booking_duration_minutes(store.bookings[sa["booking_id"]])
    store.handlers[handler_id]["scheduled_minutes_total"] = total


def add_ledger_entry(booking_id, entry_type, amount_cents, description):
    entry = new_immutable()
    entry.update({
        "booking_id": booking_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "description": description,
    })
    store.ledger_entries[entry["id"]] = entry
    return entry


def recompute_total_paid(booking):
    booking["total_paid_cents"] = sum(
        e["amount_cents"]
        for e in store.ledger_entries.values()
        if e["booking_id"] == booking["id"] and e["entry_type"] == "PAYMENT"
    )


def recompute_cert_expiry(animal):
    """current_health_cert_expires_at = max(valid_until) over PASS records; null if none."""
    valids = [
        h["valid_until"]
        for h in store.health_records.values()
        if h["animal_id"] == animal["id"] and h["result"] == "PASS" and h["valid_until"] is not None
    ]
    animal["current_health_cert_expires_at"] = max(valids) if valids else None


def cancel_cascade(booking):
    """Shared cancel cascade: release assignments, remove roster animals, detach add-ons."""
    for sa in store.staff_assignments.values():
        if sa["booking_id"] == booking["id"] and sa["status"] == "ASSIGNED":
            sa["status"] = "RELEASED"
            sa["release_reason"] = "BOOKING_CANCELLED"
            bump(sa)
            recompute_handler_minutes(sa["handler_id"])
    for ba in store.booking_animals.values():
        if ba["booking_id"] == booking["id"] and ba["status"] in ("PROPOSED", "CONFIRMED"):
            ba["status"] = "REMOVED"
            ba["removal_reason"] = "BOOKING_CANCELLED"
            bump(ba)
    for a in store.addon_requests.values():
        if a["booking_id"] == booking["id"] and a["status"] in ("REQUESTED", "APPROVED"):
            a["status"] = "REMOVED"
            bump(a)
    booking["quote_fresh"] = False


def refund_waterfall(booking, reason):
    """cancellation_refund: append REFUND/FORFEIT/PENALTY entries per variant and
    advance payment_status. When nothing was ever paid, no entries are created
    and payment_status stays UNPAID."""
    paid = booking["total_paid_cents"]
    if reason == "CUSTOMER":
        hours_before = (booking["start_time"] - now()).total_seconds() / 3600.0
        if hours_before >= 168:
            refund = paid
        elif hours_before >= 72:
            refund = rhu(Decimal("0.75") * paid)
        elif hours_before >= 24:
            refund = rhu(Decimal("0.50") * paid)
        else:
            refund = 0
    elif reason == "WEATHER":
        nonrecoverable = sum(
            1 for p in store.permits.values()
            if p["booking_id"] == booking["id"] and p["status"] in ("SUBMITTED", "ISSUED")
        )
        refund = max(0, paid - 2500 * nonrecoverable)
    else:  # COMPLIANCE
        refund = 0

    if paid == 0:
        return

    forfeit = paid - refund
    if refund > 0:
        add_ledger_entry(booking["id"], "REFUND", refund,
                         "Cancellation refund (%s)" % reason)
    if forfeit > 0:
        add_ledger_entry(booking["id"], "FORFEIT", forfeit,
                         "Cancellation forfeiture (%s)" % reason)
    if reason == "COMPLIANCE":
        penalty = rhu(COMPLIANCE_PENALTY_RATE * booking["quoted_total_cents"])
        add_ledger_entry(booking["id"], "PENALTY", penalty,
                         "Compliance cancellation penalty")

    if refund == paid:
        booking["payment_status"] = "REFUND_FULL"
    elif refund > 0:
        booking["payment_status"] = "REFUND_PARTIAL"
    else:
        booking["payment_status"] = "FORFEITED"


def cancel_booking(booking, reason, target_status):
    """Full cancellation: refund waterfall + shared cascade + status + version."""
    refund_waterfall(booking, reason)
    cancel_cascade(booking)
    booking["status"] = target_status
    bump(booking)


def remove_animal_attachments(animal, removal_reason, auto_cancel):
    """Quarantine/retire removal cascade over this animal's PROPOSED/CONFIRMED
    attachments on non-terminal bookings."""
    for ba in list(store.booking_animals.values()):
        if ba["animal_id"] != animal["id"] or ba["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        booking = store.bookings[ba["booking_id"]]
        if booking["status"] in TERMINAL_BOOKING_STATES:
            continue
        was_confirmed_booking = booking["status"] == "CONFIRMED"
        ba["status"] = "REMOVED"
        ba["removal_reason"] = removal_reason
        bump(ba)
        booking["quote_fresh"] = False
        bump(booking)
        if auto_cancel and was_confirmed_booking:
            remaining = sum(
                1 for x in store.booking_animals.values()
                if x["booking_id"] == booking["id"] and x["status"] == "CONFIRMED"
            )
            if remaining == 0:
                # Depth-3 chain: HealthRecord FAIL -> QUARANTINE -> REMOVED ->
                # Booking CANCELLED_COMPLIANCE with the COMPLIANCE refund variant.
                cancel_booking(booking, "COMPLIANCE", "CANCELLED_COMPLIANCE")


def animal_buffered_conflict(animal, booking, exclude_booking_id=None):
    """animal_rest_window: True if the booking's buffered interval intersects any
    other CONFIRMED attachment of this animal on a non-terminal booking."""
    buf = timedelta(hours=animal["rest_buffer_hours"])
    new_start = booking["start_time"] - buf
    new_end = booking["end_time"] + buf
    for ba in store.booking_animals.values():
        if ba["animal_id"] != animal["id"] or ba["status"] != "CONFIRMED":
            continue
        if exclude_booking_id is not None and ba["booking_id"] == exclude_booking_id:
            continue
        if ba["booking_id"] == booking["id"]:
            continue
        other = store.bookings[ba["booking_id"]]
        if other["status"] in TERMINAL_BOOKING_STATES:
            continue
        ex_start = other["start_time"] - buf
        ex_end = other["end_time"] + buf
        if ex_start < new_end and new_start < ex_end:
            return True
    return False


def handler_overbooked(handler_id, booking, exclude_booking_id=None):
    """handler_daily_capacity: strict overlap or > 480 aggregate minutes on the
    candidate booking's UTC calendar date."""
    new_start = booking["start_time"]
    new_end = booking["end_time"]
    new_date = new_start.date()
    new_duration = booking_duration_minutes(booking)
    total = 0
    for sa in store.staff_assignments.values():
        if sa["handler_id"] != handler_id or sa["status"] != "ASSIGNED":
            continue
        if exclude_booking_id is not None and sa["booking_id"] == exclude_booking_id:
            continue
        if sa["booking_id"] == booking["id"]:
            continue
        other = store.bookings[sa["booking_id"]]
        if other["status"] in TERMINAL_BOOKING_STATES:
            continue
        if other["start_time"].date() != new_date:
            continue
        # Strict overlap: touching at an endpoint is allowed.
        if other["start_time"] < new_end and new_start < other["end_time"]:
            return True
        total += booking_duration_minutes(other)
    return (total + new_duration) > DAILY_CAPACITY_MINUTES
