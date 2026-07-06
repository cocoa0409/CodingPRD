"""Deterministic money calculations (PRD §3.3, §3.6, §3.8, §3.7; SCAFFOLD §1.3).

All money is integer cents; every percentage/proration is rounded half up at
the exact point each rule specifies — never earlier, never later (PRD §2.5).
"""
import math
from decimal import Decimal

from util import round_half_up

SERVICE_FEE_PCT = Decimal("0.05")  # SCAFFOLD concession_order_total.constants


def reservation_pricing(showtime, occupant_count, promo_pct, has_pass):
    """Compute amount_due_cents for a reservation at creation (PRD §3.3).

    Three variants:
      - season pass: admission waived; gross = surcharge if double else 0;
        promo_pct ignored.
      - PER_CAR: base covers included_occupants; extra occupants charged
        per_extra_person_cents; +surcharge if double.
      - PER_PERSON: every occupant charged base_price_cents; +surcharge if double.
    For the non-pass variants, promo discount = round_half_up(gross * promo_pct),
    applied once to the whole gross (sum-then-round). amount_due = gross - discount.
    """
    surcharge = showtime["double_feature_surcharge_cents"] if showtime["is_double_feature"] else 0

    if has_pass:
        # Pass covers regular admission; only the double-feature surcharge is
        # charged and promo_pct is ignored.
        return surcharge

    if showtime["pricing_mode"] == "PER_CAR":
        extra_people = max(0, occupant_count - showtime["included_occupants"])
        gross = (showtime["base_price_cents"]
                 + extra_people * showtime["per_extra_person_cents"]
                 + surcharge)
    else:  # PER_PERSON
        gross = occupant_count * showtime["base_price_cents"] + surcharge

    # Discount computed on the whole gross, rounded once.
    discount = round_half_up(Decimal(gross) * Decimal(str(promo_pct)))
    return gross - discount


def voluntary_cancel_refund(amount_paid_cents, hours_before):
    """Chronological policy tier for a voluntary cancel (PRD §3.6).

    >=48h -> 100%, >=24h -> 50%, >=2h -> 25%, else 0%. Rounded half up once.
    """
    if hours_before >= 48:
        pct = Decimal("1.00")
    elif hours_before >= 24:
        pct = Decimal("0.50")
    elif hours_before >= 2:
        pct = Decimal("0.25")
    else:
        pct = Decimal("0.00")
    return round_half_up(Decimal(amount_paid_cents) * pct)


def weather_refund(amount_paid_cents, features_remaining, total_features):
    """Pro-rata weather refund by unscreened features (PRD §3.6).

    refund = round_half_up(paid * remaining / total), remaining = min(features_remaining, total).
    """
    remaining = min(features_remaining, total_features)
    return round_half_up(Decimal(amount_paid_cents) * Decimal(remaining) / Decimal(total_features))


def concession_order_total(priced_lines):
    """Compute subtotal/tax/service_fee/total (PRD §3.8; pinned rounding order).

    priced_lines: list of (unit_price_cents, qty, tax_rate) in REQUEST ORDER.
    Tax is rounded half up PER LINE then summed; service fee is rounded half up
    ONCE on the subtotal.
    """
    subtotal = 0
    tax = 0
    for unit_price_cents, qty, tax_rate in priced_lines:
        line_total = unit_price_cents * qty
        subtotal += line_total
        tax += round_half_up(Decimal(line_total) * Decimal(str(tax_rate)))
    service_fee = round_half_up(Decimal(subtotal) * SERVICE_FEE_PCT)
    total = subtotal + tax + service_fee
    return subtotal, tax, service_fee, total


def private_rental_quote(flat_venue_fee_cents, per_hour_cents, start_dt, end_dt):
    """Quote = flat fee + per_hour * ceil(duration_hours) (PRD §3.7).

    Any partial hour bills as a full hour (ceil).
    """
    seconds = (end_dt - start_dt).total_seconds()
    duration_hours = math.ceil(seconds / 3600.0)
    return flat_venue_fee_cents + per_hour_cents * duration_hours
