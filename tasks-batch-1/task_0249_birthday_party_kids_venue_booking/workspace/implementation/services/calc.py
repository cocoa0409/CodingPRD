"""Booking calculations and derived-field reconciliation (PRD section 3, SCAFFOLD section 1.3).

All money is integer cents. The only fractional input is deposit_pct, and the
deposit is taken to the next whole cent by ceiling (PRD section 2.9).

Reconciliation evaluation order is PINNED (calc deposit_due_amount):
  (1) quote_total_cents  := booking_quote_total
  (2) deposit_due_cents  := ceil(quote_total_cents * package.deposit_pct)   [while not pinned]
  (3) balance_due_cents  := applicable_total - amount_paid_cents
  (4) payment_status     := payment_status_derive
"""

import math
from datetime import timedelta

from db import db
from services.common import iso_from_dt, parse_iso8601


# ----------------------------------------------------------------------------
# Lookups for a booking's children
# ----------------------------------------------------------------------------

def active_add_ons(booking_id):
    return [a for a in db.add_ons.values()
            if a["booking_id"] == booking_id and a["status"] == "ACTIVE"]


def guest_party_events(booking_id):
    return [g for g in db.guest_parties.values() if g["booking_id"] == booking_id]


def settled_payments(booking_id):
    return [p for p in db.payments.values()
            if p["booking_id"] == booking_id and p["status"] == "SETTLED"]


# ----------------------------------------------------------------------------
# Duration / window geometry (calc room_window_occupancy)
# ----------------------------------------------------------------------------

def compute_effective_duration(booking, package):
    """package.base_duration_minutes + sum(extra_minutes * quantity) over ACTIVE EXTRA_TIME add-ons."""
    extra = 0
    for a in active_add_ons(booking["id"]):
        if a["kind"] == "EXTRA_TIME":
            extra += a["extra_minutes"] * a["quantity"]
    return package["base_duration_minutes"] + extra


def recompute_window(booking, package):
    """Recompute effective_duration_minutes and event_end_utc from current start + duration."""
    duration = compute_effective_duration(booking, package)
    booking["effective_duration_minutes"] = duration
    start = parse_iso8601(booking["event_start_utc"], "event_start_utc")
    end = start + timedelta(minutes=duration)
    booking["event_end_utc"] = iso_from_dt(end)


def booking_room_interval(booking):
    """Half-open room occupancy: [start, event_end + buffer_minutes)."""
    room = db.rooms[booking["room_id"]]
    start = parse_iso8601(booking["event_start_utc"], "event_start_utc")
    end = parse_iso8601(booking["event_end_utc"], "event_end_utc")
    buffered_end = end + timedelta(minutes=room["buffer_minutes"])
    return start, buffered_end


# ----------------------------------------------------------------------------
# Pricing — estimate variant (calc booking_quote_total)
# ----------------------------------------------------------------------------

def package_charge_for_children(package, children):
    overage = max(0, children - package["included_children"])
    return package["base_price_cents"] + overage * package["per_extra_child_cents"]


def addons_charge(booking_id):
    return sum(a["unit_price_cents"] * a["quantity"] for a in active_add_ons(booking_id))


def compute_quote_total(booking, package):
    """ESTIMATE variant: package charge on live children_count + active add-ons."""
    return (package_charge_for_children(package, booking["children_count"])
            + addons_charge(booking["id"]))


# ----------------------------------------------------------------------------
# Pricing — settlement variant (calc booking_final_total)
# ----------------------------------------------------------------------------

def compute_final_total(booking, package):
    """SETTLEMENT variant: prices overage on the PEAK realized children count.

    Replays GuestParty roster events in created_at ASC order, reconstructing the
    creation-time children count first.
    """
    events = guest_party_events(booking["id"])
    total_delta = sum(ev["children_delta"] for ev in events)
    children_at_creation = booking["children_count"] - total_delta
    running = children_at_creation
    peak = running
    for ev in sorted(events, key=lambda e: (e["created_at"], e["_seq"])):
        running += ev["children_delta"]
        if running > peak:
            peak = running
    return (package_charge_for_children(package, peak)
            + addons_charge(booking["id"]))


# ----------------------------------------------------------------------------
# Deposit (calc deposit_due_amount)
# ----------------------------------------------------------------------------

def compute_deposit_due(quote_total_cents, package):
    """ceil(quote_total_cents * deposit_pct) to whole cents."""
    raw = quote_total_cents * package["deposit_pct"]
    return int(math.ceil(round(raw, 9)))


# ----------------------------------------------------------------------------
# amount_paid / balance reconciliation (calc amount_paid_reconcile)
# ----------------------------------------------------------------------------

def compute_amount_paid(booking_id):
    paid = 0
    for p in settled_payments(booking_id):
        if p["direction"] == "CHARGE":
            paid += p["amount_cents"]
        elif p["direction"] == "REFUND":
            paid -= p["amount_cents"]
    return paid


def applicable_total(booking):
    """final_total_cents when COMPLETED, else quote_total_cents."""
    if booking["status"] == "COMPLETED":
        return booking["final_total_cents"]
    return booking["quote_total_cents"]


# ----------------------------------------------------------------------------
# Payment status (calc payment_status_derive)
# ----------------------------------------------------------------------------

def has_cancellation_refund(booking_id):
    for p in settled_payments(booking_id):
        if p["direction"] == "REFUND" and p["purpose"] == "CANCELLATION_REFUND":
            return True
    return False


def compute_payment_status(booking):
    target = applicable_total(booking)
    amount_paid = booking["amount_paid_cents"]
    deposit_due = booking["deposit_due_cents"]
    if amount_paid <= 0 and has_cancellation_refund(booking["id"]):
        return "REFUNDED"
    if amount_paid <= 0:
        return "UNPAID"
    if amount_paid >= target:
        return "PAID_IN_FULL"
    if amount_paid >= deposit_due:
        return "DEPOSIT_PAID"
    return "UNPAID"


# ----------------------------------------------------------------------------
# Full reconciliation entrypoints
# ----------------------------------------------------------------------------

def reconcile_quote(booking, package, recompute_deposit=True):
    """Pinned-order reconcile of quote -> deposit -> balance -> payment_status.

    recompute_deposit=False once the deposit has been pinned (on confirm).
    """
    booking["quote_total_cents"] = compute_quote_total(booking, package)
    if recompute_deposit:
        booking["deposit_due_cents"] = compute_deposit_due(
            booking["quote_total_cents"], package)
    reconcile_balance(booking)


def reconcile_balance(booking):
    """Recompute amount_paid -> balance_due -> payment_status."""
    booking["amount_paid_cents"] = compute_amount_paid(booking["id"])
    booking["balance_due_cents"] = applicable_total(booking) - booking["amount_paid_cents"]
    booking["payment_status"] = compute_payment_status(booking)


def reconcile_headcount(booking):
    booking["headcount_committed"] = booking["children_count"] + booking["adults_count"]
    booking["waivers_required"] = booking["children_count"]
    booking["waivers_signed"] = count_signed_waivers(booking["id"])


def count_signed_waivers(booking_id):
    return sum(1 for w in db.waivers.values()
               if w["booking_id"] == booking_id and w["status"] == "SIGNED")


def deposit_pinned(booking):
    """Deposit is pinned once the booking has been CONFIRMED at least once.

    The estimate must keep recomputing deposit while QUOTE_DRAFT/HELD; after the
    first HELD->CONFIRMED it is frozen. We track this with a private flag.
    """
    return booking.get("_deposit_pinned", False)
