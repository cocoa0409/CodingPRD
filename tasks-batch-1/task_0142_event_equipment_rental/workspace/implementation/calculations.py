"""Calculation rules (scaffold §1.3 / PRD §2.5, §3.3, §3.7, §3.9).

All money is whole-cent integers. Rounding is half-up and applied at exactly
one point: the per-unit multi-day rental price, before multiplying by quantity.
"""
from decimal import Decimal, ROUND_HALF_UP

# Delivery-fee constants (scaffold calc delivery_fee / PRD §3.3).
ZONE_BASE_CENTS = {"LOCAL": 5000, "EXTENDED": 9000, "REMOTE": 15000}
SURCHARGE_CENTS = 4000
BIG_EVENT_UNIT_THRESHOLD = 100        # >= 100 units triggers surcharge
FREE_DELIVERY_SUBTOTAL_CENTS = 200000  # >= $2000 subtotal waives the base

# Weather-sensitive categories drive RentalOrder.weather_cancellable (PRD §3.3).
WEATHER_SENSITIVE_CATEGORIES = {"TENT", "BOUNCE_HOUSE"}


def round_half_up_cents(value) -> int:
    """Round a numeric value to a whole number of cents, half up."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discounted_day_rate(daily_rate_cents: int, multi_day_discount_pct) -> int:
    """Discounted per-unit per-day rate, rounded half up to whole cents.

    disc_day = round_half_up(daily_rate_cents * (1 - multi_day_discount_pct))
    """
    pct = Decimal(str(multi_day_discount_pct))
    raw = Decimal(daily_rate_cents) * (Decimal(1) - pct)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_rental_charge(item: dict, rental_days: int, quantity: int) -> int:
    """Multi-day rental charge for a single line (scaffold calc line_rental_charge).

    Pinned evaluation order: compute the per-unit multi-day price, round it to
    whole cents, THEN multiply by quantity (round-then-multiply).
        full_day = item.daily_rate_cents
        disc_day = round_half_up(daily_rate * (1 - multi_day_discount_pct))
        per_unit_price = full_day + (d - 1) * disc_day
        line_rental_cents = per_unit_price * quantity
    """
    full_day = int(item["daily_rate_cents"])
    disc_day = discounted_day_rate(full_day, item.get("multi_day_discount_pct", 0))
    per_unit_price = full_day + (rental_days - 1) * disc_day
    return per_unit_price * quantity


def line_deposit_cents(item: dict, quantity: int) -> int:
    return quantity * int(item.get("deposit_per_unit_cents", 0))


def line_cleaning_cents(item: dict, quantity: int) -> int:
    if item.get("requires_cleaning", False):
        return quantity * int(item.get("cleaning_fee_cents", 0))
    return 0


def delivery_fee_cents(fulfillment: str, delivery_zone, total_units: int,
                       rental_subtotal_cents: int) -> int:
    """Delivery/pickup fee (scaffold calc delivery_fee / PRD §3.3).

    WILL_CALL -> 0. DELIVERY -> zone base (waived when subtotal >= $2000) plus a
    big-event surcharge when total units >= 100 (surcharge never waived).
    """
    if fulfillment == "WILL_CALL":
        return 0
    base = ZONE_BASE_CENTS.get(delivery_zone, 0)
    surcharge = SURCHARGE_CENTS if total_units >= BIG_EVENT_UNIT_THRESHOLD else 0
    base_after_waiver = 0 if rental_subtotal_cents >= FREE_DELIVERY_SUBTOTAL_CENTS else base
    return base_after_waiver + surcharge


def held_balance(ledger_entries) -> int:
    """Current held-deposit balance (scaffold calc deposit_held_balance / PRD §3.7).

    Replay the append-only stream in created_at ASC order (tie-break created_at
    only — id MUST NOT be used). HOLD adds, RELEASE/FORFEIT subtract. Never < 0
    by invariant; floored at 0 defensively.
    """
    entries = sorted(ledger_entries, key=lambda e: e["_created_seq_key"])
    held = 0
    for e in entries:
        if e["kind"] == "HOLD":
            held += int(e["amount_cents"])
        elif e["kind"] in ("RELEASE", "FORFEIT"):
            held -= int(e["amount_cents"])
    return max(held, 0)
