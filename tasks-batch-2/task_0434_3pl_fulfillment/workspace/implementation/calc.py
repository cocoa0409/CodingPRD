"""Calculation rules (PRD §2.9, §3.6, §3.7, §3.8, §3.10, §3.11).

All handling arithmetic is pure integer cents (no rounding). The single fractional
step is the carrier discount in rate-shop, where round_half_up applies once per
carrier after the discount.
"""
from decimal import Decimal, ROUND_HALF_UP

# Cartonization box inner volumes (PRD §3.6 / SCAFFOLD constants).
SMALL_INNER_CC = 1000
MEDIUM_INNER_CC = 5000
LARGE_INNER_CC = 20000

# Carrier rate cards (PRD §3.7 / SCAFFOLD constants), in integer cents.
CARRIER_RATES = {
    "GROUND_ECONOMY": {"base_cents": 300, "per_zone_cents": 50, "per_carton_cents": 100},
    "GROUND_PLUS": {"base_cents": 500, "per_zone_cents": 40, "per_carton_cents": 120},
    "AIR_EXPRESS": {"base_cents": 1200, "per_zone_cents": 80, "per_carton_cents": 150},
}

# Fixed carrier precedence list for tie-breaking (PRD §3.7).
CARRIER_PRECEDENCE = ["GROUND_ECONOMY", "GROUND_PLUS", "AIR_EXPRESS"]

FIRST_UNIT_INCLUDED = 1
FIRST_CARTON_INCLUDED = 1


def estimated_handling_cents(client, total_units):
    """PRD §3.6 — unit-only basis, no carton surcharge.

    base + (total_units > 1 ? (total_units - 1) * per_extra_unit : 0)
    """
    base = client["handling_rate_per_order_cents"]
    if total_units > FIRST_UNIT_INCLUDED:
        unit_component = (total_units - FIRST_UNIT_INCLUDED) * client["handling_rate_per_extra_unit_cents"]
    else:
        unit_component = 0
    return base + unit_component


def billed_handling_cents(client, total_units, carton_count):
    """PRD §3.8 — estimate basis PLUS a per-extra-carton surcharge.

    base + unit_component + (carton_count > 1 ? (carton_count - 1) * surcharge : 0)
    """
    base = client["handling_rate_per_order_cents"]
    if total_units > FIRST_UNIT_INCLUDED:
        unit_component = (total_units - FIRST_UNIT_INCLUDED) * client["handling_rate_per_extra_unit_cents"]
    else:
        unit_component = 0
    if carton_count > FIRST_CARTON_INCLUDED:
        carton_component = (carton_count - FIRST_CARTON_INCLUDED) * client["handling_surcharge_per_extra_carton_cents"]
    else:
        carton_component = 0
    return base + unit_component + carton_component


def cartonization_size(fill_volume_cc):
    """PRD §3.6 — smallest box whose inner_cc >= fill, ascending. Inclusive boundary.

    Returns the carton_size string, or None when it overflows LARGE.
    """
    if fill_volume_cc <= SMALL_INNER_CC:
        return "SMALL"
    elif fill_volume_cc <= MEDIUM_INNER_CC:
        return "MEDIUM"
    elif fill_volume_cc <= LARGE_INNER_CC:
        return "LARGE"
    return None


def _round_half_up(exact_decimal):
    return int(exact_decimal.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def published_quote_cents(carrier, ship_to_zone, carton_count):
    """PRD §3.7 — exact integer list-price quote for a carrier."""
    rate = CARRIER_RATES[carrier]
    return (
        rate["base_cents"]
        + rate["per_zone_cents"] * ship_to_zone
        + rate["per_carton_cents"] * carton_count
    )


def negotiated_quote_cents(published_cents, carrier_discount_bps):
    """PRD §3.7 — discount-then-round_half_up, single rounding per carrier.

    negotiated_exact = published * (10000 - bps) / 10000
    negotiated = round_half_up(negotiated_exact)
    """
    exact = (Decimal(published_cents) * Decimal(10000 - carrier_discount_bps)) / Decimal(10000)
    return _round_half_up(exact)


def rate_shop(eligible_carriers, ship_to_zone, carton_count, carrier_discount_bps):
    """PRD §3.7 — rank eligible carriers by negotiated quote, lowest wins.

    Tie-break by fixed precedence list. Returns (carrier, negotiated_cents).
    `eligible_carriers` is the candidate set after the hazmat eligibility filter.
    """
    best_carrier = None
    best_cost = None
    # Evaluate in fixed precedence order so the first-seen lowest wins ties
    # deterministically (earlier in the precedence list).
    for carrier in CARRIER_PRECEDENCE:
        if carrier not in eligible_carriers:
            continue
        published = published_quote_cents(carrier, ship_to_zone, carton_count)
        negotiated = negotiated_quote_cents(published, carrier_discount_bps)
        if best_cost is None or negotiated < best_cost:
            best_cost = negotiated
            best_carrier = carrier
    return best_carrier, best_cost
