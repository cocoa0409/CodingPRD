"""order_fee_breakdown and promo_discount (PRD §3.4).

Pinned order of operations:
  (1) per-ticket fee from the UNDISCOUNTED face value, rounded once per ticket
  (2) line and order aggregation
  (3) discount from the subtotal
  (4) buyer and organiser totals from the fee mode
Nothing propagates backwards.
"""
from decimal import Decimal

from services import constants as C
from services.money import cents


def per_ticket_fee_cents(face_cents):
    if face_cents <= C.FEE_TIER_1_MAX_FACE_CENTS:
        rate = C.FEE_TIER_1_RATE
    elif face_cents <= C.FEE_TIER_2_MAX_FACE_CENTS:
        rate = C.FEE_TIER_2_RATE
    else:
        rate = C.FEE_TIER_3_RATE
    raw = cents(Decimal(face_cents) * rate) + C.PLATFORM_FEE_FLAT_CENTS
    return min(max(raw, C.PLATFORM_FEE_MIN_CENTS), C.PLATFORM_FEE_CAP_CENTS)


def line_amounts(face_cents, quantity):
    fee = per_ticket_fee_cents(face_cents)
    return {
        "unit_price_cents": face_cents,
        "per_ticket_fee_cents": fee,
        "line_face_cents": face_cents * quantity,
        "line_fee_cents": fee * quantity,
    }


def discount_cents(subtotal_cents, promo):
    """The smallest of the raw entitlement, the 30% ceiling and the subtotal."""
    if promo["kind"] == "PERCENT":
        raw = cents(Decimal(subtotal_cents) * Decimal(promo["percent_bp"]) / Decimal(10000))
    else:
        raw = promo["amount_cents"]
    cap = cents(Decimal(subtotal_cents) * C.PROMO_MAX_DISCOUNT_PCT)
    return min(raw, cap, subtotal_cents)


def totals(fee_mode, subtotal, discount, fee_total):
    """Variant selection on Event.fee_mode."""
    if fee_mode == "ABSORB":
        return {
            "buyer_total_cents": subtotal - discount,
            "organizer_gross_cents": subtotal - discount - fee_total,
        }
    return {
        "buyer_total_cents": subtotal - discount + fee_total,
        "organizer_gross_cents": subtotal - discount,
    }
