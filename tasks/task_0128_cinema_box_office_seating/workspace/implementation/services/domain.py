"""Core domain logic for the Cinema Box Office & Seating API.

Holds the pricing engine, loyalty/tier derivation, the hold-expiry sweep, the
computed-field projector for showtimes/seats, and all state transitions with
their cascades (open/cancel/close showtimes; create/pay/cancel/refund/exchange
orders; expire held orders).
"""
from __future__ import annotations

from decimal import Decimal
from datetime import timedelta
from typing import Optional

import clock
import db
from errors import APIError
import errors as E
from services.common import round_half_up, touch, new_common_fields, new_lean_fields

# ---- constants (SCAFFOLD §1.3) ---------------------------------------------
PROFILE_MULT = {
    "STANDARD": Decimal("1.00"),
    "MATINEE": Decimal("0.70"),
    "PEAK": Decimal("1.30"),
}
CLASS_SURCHARGE = {  # cents
    "STANDARD": 0,
    "PREMIUM": 400,
    "ACCESSIBLE": 0,
}
MATINEE_CUTOFF_HOUR = 17
HOLD_TTL_MINUTES = 15
TRAILER_PAD_MINUTES = 15
POINTS_PER_CENT_DIVISOR = 100
TIER_THRESHOLDS = {"SILVER": 50, "GOLD": 200}
RENTAL_HOUSE_DISTRIBUTOR_PCT = Decimal("0.10")


# ============================================================================
# Pricing
# ============================================================================
def seat_price(showtime: dict, seat: dict) -> int:
    """profile-adjusted base (round_half_up) + integer seat-class surcharge.

    Used for both the provisional quote (at hold) and the final lock (at pay),
    differing only in WHEN the showtime profile/base is read.
    """
    profile = showtime["pricing_profile"]
    mult = PROFILE_MULT[profile]
    base = showtime["base_price_cents"]
    adjusted = round_half_up(Decimal(base) * mult)
    return adjusted + CLASS_SURCHARGE[seat["seat_class"]]


# ============================================================================
# Loyalty / tier
# ============================================================================
def points_for_subtotal(tickets_subtotal_cents: int) -> int:
    """floor(subtotal / 100) — combos earn nothing (PRD §3.3, §3.5)."""
    return tickets_subtotal_cents // POINTS_PER_CENT_DIVISOR


def derive_tier(points: int) -> str:
    if points >= TIER_THRESHOLDS["GOLD"]:
        return "GOLD"
    if points >= TIER_THRESHOLDS["SILVER"]:
        return "SILVER"
    return "BRONZE"


def apply_points_delta(member: dict, delta: int) -> None:
    """Adjust lifetime loyalty_points and re-derive tier (PRD §3.3)."""
    member["loyalty_points"] = member.get("loyalty_points", 0) + delta
    member["tier"] = derive_tier(member["loyalty_points"])
    touch(member)


# ============================================================================
# Time helpers
# ============================================================================
def showtime_starts_at(showtime: dict):
    from services.common import parse_iso
    return parse_iso(showtime["starts_at"])


def showtime_ends_at(showtime: dict):
    from services.common import parse_iso
    return parse_iso(showtime["ends_at"])


# ============================================================================
# Hold expiry (PRD §3.6)
# ============================================================================
def expire_order(order: dict) -> None:
    """HELD -> EXPIRED: void tickets, free seats, bump showtime version."""
    from services.common import parse_iso
    order["status"] = "EXPIRED"
    _void_tickets_and_free_seats(order)
    touch(order)
    st = db.showtimes.get(order["showtime_id"])
    if st is not None:
        touch(st)


def maybe_expire_order(order: dict) -> None:
    """Lazily expire a single HELD order if its hold clock has lapsed."""
    if order["status"] != "HELD":
        return
    from services.common import parse_iso
    if clock.now() >= parse_iso(order["hold_expires_at"]):
        expire_order(order)


def expire_sweep() -> None:
    """Expire every HELD order whose hold_expires_at has been reached/passed."""
    from services.common import parse_iso
    now = clock.now()
    for order in list(db.orders.values()):
        if order["status"] == "HELD" and now >= parse_iso(order["hold_expires_at"]):
            expire_order(order)


def expire_showtime_holds(showtime_id: str) -> None:
    """Lazily expire any past-TTL HELD orders on a given showtime (read-path)."""
    from services.common import parse_iso
    now = clock.now()
    for order in list(db.orders.values()):
        if order["showtime_id"] == showtime_id and order["status"] == "HELD":
            if now >= parse_iso(order["hold_expires_at"]):
                expire_order(order)


# ============================================================================
# Ticket / seat cascade primitives
# ============================================================================
def order_tickets(order_id: str) -> list:
    return [t for t in db.tickets.values() if t["order_id"] == order_id]


def _void_tickets_and_free_seats(order: dict) -> None:
    """Void every (non-VOIDED) ticket on the order; free its bound seat."""
    for t in order_tickets(order["id"]):
        if t["state"] != "VOIDED":
            t["state"] = "VOIDED"
            touch(t)
            seat = db.seats.get(t["seat_id"])
            if seat is not None:
                seat["occupancy"] = "FREE"


# ============================================================================
# Computed showtime / seat projection (read-time)
# ============================================================================
def project_seat(seat: dict) -> dict:
    """occupancy is derived from the live ticket bound to this seat."""
    occ = "FREE"
    for t in db.tickets.values():
        if t["seat_id"] != seat["id"]:
            continue
        if t["state"] == "SOLD":
            occ = "SOLD"
            break
        if t["state"] == "HELD":
            occ = "HELD"
    out = dict(seat)
    out["occupancy"] = occ
    return out


def project_showtime(showtime: dict) -> dict:
    """Attach computed seat counts and gross receipts (PRD §2.6)."""
    sold = 0
    held = 0
    gross = 0
    for t in db.tickets.values():
        if t["showtime_id"] != showtime["id"]:
            continue
        if t["state"] == "SOLD":
            sold += 1
            gross += t.get("final_price_cents") or 0
        elif t["state"] == "HELD":
            held += 1
    out = dict(showtime)
    out["seats_sold"] = sold
    out["seats_held"] = held
    out["gross_receipts_cents"] = gross
    return out


def current_gross_receipts(showtime_id: str) -> int:
    """Sum final_price_cents over SOLD tickets on a showtime."""
    return sum(
        (t.get("final_price_cents") or 0)
        for t in db.tickets.values()
        if t["showtime_id"] == showtime_id and t["state"] == "SOLD"
    )


# ============================================================================
# Order total computation (PRD §3.5) — pinned order of operations
# ============================================================================
def compute_combos_subtotal(member: dict, combo_ids: list) -> int:
    """Per-combo discount (rounded) then summed; discount only for SILVER/GOLD."""
    tier = member.get("tier", "BRONZE")
    total = 0
    for cid in combo_ids:
        combo = db.combos[cid]
        if tier in ("SILVER", "GOLD"):
            discount = round_half_up(Decimal(combo["price_cents"]) * Decimal(str(combo["member_discount_pct"])))
            total += combo["price_cents"] - discount
        else:
            total += combo["price_cents"]
    return total


# ============================================================================
# Refund of a single PAID order (shared by /refund and showtime-cancel cascade)
# ============================================================================
def refund_paid_order(order: dict, destination: str, *, from_cascade: bool = False) -> None:
    """PAID -> REFUNDED cascade (PRD §3.7).

    Payment refunded, optional wallet credit, tickets voided + seats freed,
    loyalty reversed, member tier re-derived. Showtime version bump handled by
    the caller's broader transition where appropriate; here we bump it too so a
    standalone refund advances the anchor.
    """
    order["status"] = "REFUNDED"

    # payment cascade (depth-1)
    payment = _order_payment(order["id"])
    refund_amount = payment["amount_cents"] if payment else order.get("total_charged_cents", 0)
    if payment is not None:
        payment["refunded_cents"] = payment.get("refunded_cents", 0) + refund_amount
        payment["status"] = "REFUNDED"
        touch(payment)

    # wallet credit (depth-2/3)
    if destination == "WALLET":
        member = db.members.get(order["member_id"])
        if member is not None:
            member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) + refund_amount
            touch(member)

    # tickets voided + seats freed
    _void_tickets_and_free_seats(order)

    # loyalty reversal
    member = db.members.get(order["member_id"])
    if member is not None:
        apply_points_delta(member, -order.get("_accrued_points", 0))

    touch(order)

    if not from_cascade:
        st = db.showtimes.get(order["showtime_id"])
        if st is not None:
            touch(st)


def _order_payment(order_id: str) -> Optional[dict]:
    for p in db.payments.values():
        if p["order_id"] == order_id:
            return p
    return None
