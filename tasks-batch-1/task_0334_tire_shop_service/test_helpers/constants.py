"""Domain thresholds — numeric constants from the Tire Shop & Service PRD.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Tax (PRD §3.2 — taxable base * 8.25 percent, single round-half-up)
TAX_RATE = 0.0825

# Tire disposal fee marginal brackets (PRD §3.3)
DISPOSAL_FEE_T1_CENTS = 350   # tires 1..4
DISPOSAL_FEE_T2_CENTS = 250   # tires 5..8
DISPOSAL_FEE_T3_CENTS = 150   # tires 9+

# Road-hazard premium (PRD §3.4)
ROAD_HAZARD_PCT = 0.12
ROAD_HAZARD_FLOOR_PER_TIRE_CENTS = 1200

# Mileage-warranty proration / wear bar (PRD §3.9)
WEAR_BAR_THRESHOLD_32NDS = 2

# Special-order deposit (PRD §3.8)
SPECIAL_ORDER_DEPOSIT_PCT = 0.25
SPECIAL_ORDER_MIN_DEPOSIT_CENTS = 2000


def round_half_up(value: float) -> int:
    """Round half away from zero to a whole cent (PRD §2.5)."""
    import math
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def disposal_fee_total(n: int) -> int:
    """Marginal-bracket disposal fee for n total non-VOID tires (PRD §3.3)."""
    return (
        min(n, 4) * DISPOSAL_FEE_T1_CENTS
        + max(0, min(n - 4, 4)) * DISPOSAL_FEE_T2_CENTS
        + max(n - 8, 0) * DISPOSAL_FEE_T3_CENTS
    )


def road_hazard_premium(extended_cents: int, quantity: int) -> int:
    """Per-line road-hazard premium = max(pct term, per-tire floor) (PRD §3.4)."""
    pct = round_half_up(extended_cents * ROAD_HAZARD_PCT)
    floor = quantity * ROAD_HAZARD_FLOOR_PER_TIRE_CENTS
    return max(pct, floor)


def special_order_deposit(unit_price_cents: int, requested_quantity: int) -> int:
    """Special-order deposit = max(pct of goods value, min floor) (PRD §3.8)."""
    goods_value = unit_price_cents * requested_quantity
    pct = round_half_up(goods_value * SPECIAL_ORDER_DEPOSIT_PCT)
    return max(pct, SPECIAL_ORDER_MIN_DEPOSIT_CENTS)


def mileage_based_credit(unit_price_cents: int, warranty_miles: int,
                         miles_driven: int, claim_quantity: int) -> int:
    """Mileage-based proration credit (PRD §3.9, the variant the system applies)."""
    remaining_frac = 1 - (miles_driven / warranty_miles)
    per_tire = round_half_up(unit_price_cents * remaining_frac)
    return per_tire * claim_quantity
