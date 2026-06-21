"""Calculation rules (SCAFFOLD §1.3, PRD §3).

All money is integer cents. Fractional intermediates are truncated toward zero
(floor for non-negative values) at the point the spec names. We use math.floor on
non-negative products, which equals truncation toward zero for non-negative inputs.
"""
import math

# constants
DEMAND_SLOPE = 0.50
BUYER_FEE_RATE = 0.12
SELLER_FEE_RATES = {
    "NEW": 0.15,
    "VERIFIED": 0.12,
    "TRUSTED": 0.10,
    "RESTRICTED": 0.20,
}
LOYALTY_THRESHOLD = 3
BONUS_MULTIPLIER = 1.10
STANDARD_WINDOW_MINUTES = 1440
LAST_MINUTE_WINDOW_MINUTES = 30
GOUGE_RATIO = 2.5


def _floor(x):
    return int(math.floor(x))


def price_cap(face_value_cents, price_cap_multiplier):
    """cap = floor(face * price_cap_multiplier)."""
    return _floor(face_value_cents * price_cap_multiplier)


def effective_listing_price(listing, section, event):
    """effective_price_cents per SCAFFOLD calc effective_listing_price.

    Evaluation order pinned: scarcity -> floor -> cap.
    """
    face = section["face_value_cents"]
    cap = price_cap(face, event["price_cap_multiplier"])
    if listing["pricing_mode"] == "FIXED":
        raw = listing["ask_price_cents"]
    else:  # DYNAMIC
        total = listing["total_seat_count"]
        available = listing["available_seat_count"]
        if total > 0:
            sold_ratio = (total - available) / total
        else:
            sold_ratio = 0.0
        demand_mult = 1.0 + DEMAND_SLOPE * sold_ratio
        scaled = _floor(listing["ask_price_cents"] * demand_mult)
        floor_cents = listing.get("dynamic_floor_cents") or 0
        raw = max(floor_cents, scaled)
    return min(raw, cap)


def buyer_charge(quantity, locked_unit_price_cents, elected_credit, wallet_at_eval):
    """Return (buyer_fee_cents, total_cents, applied_credit_cents).

    base = quantity * locked_unit_price_cents
    buyer_fee_cents = floor(base * BUYER_FEE_RATE)
    gross = base + buyer_fee_cents
    applied = min(elected_credit, gross, wallet_at_eval)
    total = gross - applied
    """
    base = quantity * locked_unit_price_cents
    buyer_fee_cents = _floor(base * BUYER_FEE_RATE)
    gross = base + buyer_fee_cents
    applied = min(elected_credit, gross, wallet_at_eval)
    if applied < 0:
        applied = 0
    total = gross - applied
    return buyer_fee_cents, total, applied


def seller_fee(quantity, locked_unit_price_cents, trust_tier):
    """Return (gross_sale_cents, seller_fee_rate, seller_fee_cents)."""
    gross_sale_cents = quantity * locked_unit_price_cents
    rate = SELLER_FEE_RATES[trust_tier]
    fee = _floor(gross_sale_cents * rate)
    return gross_sale_cents, rate, fee


def event_credit_amount(final_total_cents, event_status, lifetime_orders_count):
    """Return (amount_cents, bonus_applied)."""
    base = final_total_cents
    if event_status == "CANCELLED":
        if lifetime_orders_count >= LOYALTY_THRESHOLD:
            return _floor(base * BONUS_MULTIPLIER), True
        return base, False
    return base, False


def transfer_is_last_minute(now, doors_open_at, last_minute_cutoff_minutes):
    """is_last_minute = now >= doors_open_at - cutoff."""
    from datetime import timedelta
    threshold = doors_open_at - timedelta(minutes=last_minute_cutoff_minutes)
    return now >= threshold


def transfer_deadline(now, is_last_minute, doors_open_at):
    """deadline_at per SCAFFOLD calc transfer_deadline (minute resolution)."""
    from datetime import timedelta
    if not is_last_minute:
        return now + timedelta(minutes=STANDARD_WINDOW_MINUTES)
    candidate = now + timedelta(minutes=LAST_MINUTE_WINDOW_MINUTES)
    return min(candidate, doors_open_at)


def order_lifecycle_rollup(payment_status, delivery_status):
    """Derived rollup. Payment axis evaluated first."""
    if payment_status in ("REFUNDED", "CREDITED"):
        return "UNWOUND"
    if payment_status == "CHARGED" and delivery_status in ("DELIVERED", "REPLACED"):
        return "SETTLED"
    return "OPEN"


def fraud_severity(signal, listing_effective_price_cents, section_face_value_cents):
    """Severity from signal (+ price band for PRICE_GOUGE)."""
    if signal == "DUPLICATE_BARCODE":
        return "HIGH"
    if signal == "CHARGEBACK":
        return "HIGH"
    if signal == "PRICE_GOUGE":
        band = _floor(section_face_value_cents * GOUGE_RATIO)
        if listing_effective_price_cents is not None and listing_effective_price_cents > band:
            return "HIGH"
        return "LOW"
    # VELOCITY
    return "LOW"
