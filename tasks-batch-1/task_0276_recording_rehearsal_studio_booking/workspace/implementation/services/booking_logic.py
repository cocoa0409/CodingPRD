"""Shared booking-domain logic: overlaps, charges, refunds, cascades.

These helpers are pure functions over the in-memory store, used by the route
modules. They encode the state-machine side effects from PRD §3.
"""
from db import db
from errors import err
from helpers import touch
from timeutil import parse_iso, add_minutes
from services import calc


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def booking_window(booking):
    """Return (start_dt, end_dt) of a booking as UTC-aware datetimes."""
    return parse_iso(booking["start_at"]), parse_iso(booking["end_at"])


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def room_footprint(booking, room):
    """Buffered occupancy footprint [start_at, end_at + turnaround) (PRD §2.9)."""
    start, end = booking_window(booking)
    end_buffered = add_minutes(end, room["turnaround_minutes"])
    return start, end_buffered


# ---------------------------------------------------------------------------
# amount_paid recompute (PRD §3.6)
# ---------------------------------------------------------------------------

def recompute_amount_paid(booking):
    """Sum of non-reversed inbound (DEPOSIT/BALANCE) payments."""
    total = 0
    for p in db.payments.values():
        if p["booking_id"] != booking["id"]:
            continue
        if p["kind"] in ("DEPOSIT", "BALANCE") and not p["reversed"]:
            total += p["amount_cents"]
    booking["amount_paid_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Children accessors
# ---------------------------------------------------------------------------

def gear_rentals_of(booking_id):
    return [r for r in db.gear_rentals.values() if r["booking_id"] == booking_id]


def engineer_assignments_of(booking_id):
    return [a for a in db.engineer_assignments.values() if a["booking_id"] == booking_id]


def payments_of(booking_id):
    return [p for p in db.payments.values() if p["booking_id"] == booking_id]


# ---------------------------------------------------------------------------
# Total reconciliation (PRD §3.3)
# ---------------------------------------------------------------------------

def reconcile_total(booking):
    """total = base + sum(gear) + sum(engineer at billed) + overtime."""
    gear_sum = sum(r["charge_cents"] for r in gear_rentals_of(booking["id"]) if r["status"] != "RELEASED")
    eng_sum = sum(a["charge_cents"] for a in engineer_assignments_of(booking["id"]) if a["status"] != "RELEASED")
    booking["total_charge_cents"] = (
        booking["base_charge_cents"] + gear_sum + eng_sum + booking["overtime_cents"]
    )
    return booking["total_charge_cents"]


# ---------------------------------------------------------------------------
# Cascade releases (PRD §2.8 / §3.7)
# ---------------------------------------------------------------------------

def release_children(booking):
    """Release every RESERVED gear rental and ASSIGNED engineer assignment.

    Each cascade is a real mutation: child's version increments and updated_at
    refreshes (PRD §2.8).
    """
    for rental in gear_rentals_of(booking["id"]):
        if rental["status"] == "RESERVED":
            rental["status"] = "RELEASED"
            touch(rental)
    for assign in engineer_assignments_of(booking["id"]):
        if assign["status"] == "ASSIGNED":
            assign["status"] = "RELEASED"
            touch(assign)


# ---------------------------------------------------------------------------
# Refund branch (PRD §3.7)
# ---------------------------------------------------------------------------

def compute_refund_cents(booking, studio):
    """Tiered cancellation refund (PRD §3.7 / cancellation_refund calc)."""
    amount_paid = booking["amount_paid_cents"]
    if booking["schedule_status"] == "HELD":
        return amount_paid
    start, _ = booking_window(booking)
    from db import clock_now
    hours_before = (start - clock_now()).total_seconds() / 3600.0
    if hours_before >= studio["cancellation_tier_hours"]:
        return amount_paid
    fee = calc.cancellation_fee_cents(booking["base_charge_cents"], studio["late_cancel_fee_pct"])
    return max(0, amount_paid - fee)


def perform_cancellation(booking, studio, acting_client_id):
    """Drive the full cancel cascade: refund, release children, settlement.

    Used by cancel endpoint, sweep, and lockout terminate. `acting_client_id`
    is the booking's own client for the refund Payment.client_id.
    """
    # Ensure amount_paid reflects current ledger before computing the refund.
    recompute_amount_paid(booking)
    refund_cents = compute_refund_cents(booking, studio)

    # Release children (each its own version bump).
    release_children(booking)

    deposit_was_paid = booking["settlement_status"] in ("DEPOSIT_PAID", "BALANCE_DUE", "SETTLED")

    # Settlement axis: drive through REFUNDING -> REFUNDED only if money moved
    # or a deposit had been paid. PRD §3.7: "if any money had been paid".
    if booking["amount_paid_cents"] > 0:
        booking["settlement_status"] = "REFUNDING"
        # mark prior inbound payments reversed (refunded)
        for p in payments_of(booking["id"]):
            if p["kind"] in ("DEPOSIT", "BALANCE") and not p["reversed"]:
                p["reversed"] = True
                touch(p)
        if refund_cents > 0:
            _create_refund_payment(booking, acting_client_id, refund_cents, studio)
        booking["settlement_status"] = "REFUNDED"
    elif deposit_was_paid:
        booking["settlement_status"] = "REFUNDING"
        booking["settlement_status"] = "REFUNDED"

    booking["schedule_status"] = "CANCELLED"
    booking["hold_expires_at"] = None
    touch(booking)


def _create_refund_payment(booking, client_id, refund_cents, studio):
    """Create a WALLET REFUND payment and credit the client's wallet."""
    from helpers import stamp_common
    payment = {
        "booking_id": booking["id"],
        "client_id": client_id,
        "kind": "REFUND",
        "amount_cents": refund_cents,
        "refund_destination": "WALLET",
        "reversed": False,
    }
    stamp_common(payment)
    db.payments[payment["id"]] = payment
    # Credit the wallet (PRD §3.7: refund lands in wallet -> wallet_credit_cents up).
    client = db.clients.get(client_id)
    if client is not None:
        client["wallet_credit_cents"] += refund_cents
        touch(client)
    return payment
