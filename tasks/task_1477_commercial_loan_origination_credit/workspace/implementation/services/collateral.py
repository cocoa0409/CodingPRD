"""Collateral valuation: dual-basis eligible values (calculations.eligible_collateral_value)."""
from decimal import Decimal

from services.money import floor_cents

ADVANCE_RATE = {
    "REAL_ESTATE": Decimal("0.75"),
    "EQUIPMENT": Decimal("0.80"),
    "RECEIVABLES": Decimal("0.50"),
    "INVENTORY": Decimal("0.50"),
    "AGRICULTURAL": Decimal("0.70"),
}
LIQUIDATION_HAIRCUT = Decimal("0.85")

COLLATERAL_CLASSES = set(ADVANCE_RATE.keys())


def compute_eligible_values(appraised_value_cents, orderly_liquidation_value_cents, collateral_class):
    rate = ADVANCE_RATE[collateral_class]
    eligible = floor_cents(Decimal(appraised_value_cents) * rate)
    liquidation = floor_cents(Decimal(orderly_liquidation_value_cents) * LIQUIDATION_HAIRCUT * rate)
    return eligible, liquidation
