"""Core stateful business logic: seat ledger, donations, event OPEN<->FULL
flips, payment amount recompute, and the cancellation/closing/event-cancel
cascades. Operates directly on the in-memory db dicts.
"""
import db
import models
from services import calc

# Seat-ledger membership sets (PRD §2.8).
RESERVATION_SEAT_STATES = {"HELD", "CONFIRMED", "CHECKED_IN"}
WALKIN_SEAT_STATES = {"REGISTERED", "CHECKED_IN"}


def event_reservations(event_id):
    return [r for r in db.reservations.values() if r["event_id"] == event_id]


def event_walk_ins(event_id):
    return [w for w in db.walk_ins.values() if w["event_id"] == event_id]


def reservation_attendees(reservation_id):
    return [a for a in db.attendees.values() if a["reservation_id"] == reservation_id]


def reservation_payments(reservation_id):
    return [p for p in db.payments.values() if p["reservation_id"] == reservation_id]


def recompute_seat_ledger(event):
    """event_seat_ledger (SCAFFOLD §1.3). Recompute the three derived seat
    fields from current reservations and walk-ins. Does NOT itself flip status
    or bump version."""
    seats_reserved = sum(
        r["seats"] for r in event_reservations(event["id"])
        if r["status"] in RESERVATION_SEAT_STATES
    )
    walk_in_seats = sum(
        w["party_size"] for w in event_walk_ins(event["id"])
        if w["status"] in WALKIN_SEAT_STATES
    )
    event["seats_reserved"] = seats_reserved
    event["walk_in_seats"] = walk_in_seats
    event["seats_available"] = max(
        0, event["seats_capacity"] - seats_reserved - walk_in_seats
    )


def recompute_pledged_donation(event):
    """Provisional pledged donation over HELD+CONFIRMED reservations
    (FUNDRAISER only). 0 for non-fundraiser events."""
    if event["event_type"] != "FUNDRAISER":
        event["pledged_donation_cents"] = 0
        return
    base_sum = sum(
        r["total_cents"] for r in event_reservations(event["id"])
        if r["status"] in {"HELD", "CONFIRMED"}
    )
    event["pledged_donation_cents"] = calc.donation_cents(
        base_sum, event["fundraiser_donation_pct"]
    )


def compute_settled_donation(event):
    """Final settled donation over CHECKED_IN reservations, at close."""
    if event["event_type"] != "FUNDRAISER":
        event["settled_donation_cents"] = 0
        return
    base_sum = sum(
        r["total_cents"] for r in event_reservations(event["id"])
        if r["status"] == "CHECKED_IN"
    )
    event["settled_donation_cents"] = calc.donation_cents(
        base_sum, event["fundraiser_donation_pct"]
    )


def apply_full_flip(event):
    """OPEN <-> FULL auto-flip based on seats_available. System-driven; not a
    version bump on its own (it is part of a seat-consuming/releasing mutation
    that already bumps version)."""
    if event["status"] == "OPEN" and event["seats_available"] == 0:
        event["status"] = "FULL"
    elif event["status"] == "FULL" and event["seats_available"] > 0:
        event["status"] = "OPEN"


def recompute_amount_paid(reservation):
    reservation["amount_paid_cents"] = sum(
        p["amount_cents"] for p in reservation_payments(reservation["id"])
        if p["status"] == "SETTLED"
    )


def reverse_card_payments_and_refund(reservation):
    """If reservation.payment_status == PAID, reverse its SETTLED CARD payments
    and set payment_status -> REFUNDED. (Cancellation cascade hop 2.)"""
    if reservation["payment_status"] != "PAID":
        return
    for p in reservation_payments(reservation["id"]):
        if p["status"] == "SETTLED" and p["method"] == "CARD":
            p["status"] = "REVERSED"
            models.touch(p)
    reservation["payment_status"] = "REFUNDED"
    recompute_amount_paid(reservation)
