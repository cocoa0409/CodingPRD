"""Calculation rules (SCAFFOLD Table 1.3 / PRD 3.6, 3.7, 3.11).

All amounts are integer cents. Use Decimal for fractional-cent intermediates and
round half up to whole cents per PRD 2.6.
"""
from decimal import Decimal

from common import round_half_up

# Constants (from SCAFFOLD calculations[].constants and PRD 3.x prose).
COVERAGE_CAP_PCT = 80
OXY_FLOOR_CENTS = 5000
OXY_CEIL_CENTS = 20000
USED_PCT = 75
RENTAL_CAP_MONTHS = 13
RESUPPLY_WINDOW_DAYS = 90
AUTH_VALIDITY_DAYS = 60


def modifier_adjusted_monthly(item, order):
    """Modifier-adjusted monthly allowed amount in whole cents (PRD 3.7).

    coverage_pct: KX -> 100; else requires_cmn -> 80; else 100.
    raw = base * coverage_pct / 100 (may be fractional cents).
    OXYGEN category: clamp raw into [OXY_FLOOR_CENTS, OXY_CEIL_CENTS].
    Then round_half_up to whole cents.
    """
    base = Decimal(item["monthly_rental_cents"])
    if order["modifier"] == "KX":
        coverage_pct = 100
    elif item["requires_cmn"]:
        coverage_pct = COVERAGE_CAP_PCT
    else:
        coverage_pct = 100

    raw = base * Decimal(coverage_pct) / Decimal(100)

    if item["billing_category"] == "OXYGEN":
        if raw < Decimal(OXY_FLOOR_CENTS):
            adjusted = Decimal(OXY_FLOOR_CENTS)
        elif raw > Decimal(OXY_CEIL_CENTS):
            adjusted = Decimal(OXY_CEIL_CENTS)
        else:
            adjusted = raw
    else:
        adjusted = raw

    return round_half_up(adjusted)


def purchase_allowed_amount(item, order):
    """Purchase claim-line allowed amount in whole cents (PRD 3.6).

    NU -> full purchase_price_cents exactly.
    Otherwise -> 75% of purchase_price_cents, rounded half up.
    """
    base = Decimal(item["purchase_price_cents"])
    if order["modifier"] == "NU":
        return int(base)
    return round_half_up(base * Decimal(USED_PCT) / Decimal(100))
