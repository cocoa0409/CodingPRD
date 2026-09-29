"""Domain constants and the calculation rules of PRD 2.6, 2.9, 3.3, 3.7 and 3.9."""
from decimal import Decimal

from store import D, ceil_div, r0, r2, r4

CONTRACT_UNIT_BUSHELS = Decimal(5000)

INITIAL_MARGIN_USD_PER_LOT = {
    "CORN": Decimal("1650.00"),
    "SOYBEANS": Decimal("3300.00"),
    "HRW_WHEAT": Decimal("2200.00"),
}
MAINTENANCE_MARGIN_USD_PER_LOT = {
    "CORN": Decimal("1500.00"),
    "SOYBEANS": Decimal("3000.00"),
    "HRW_WHEAT": Decimal("2000.00"),
}

MARGIN_CALL_CURE_HOURS = 24
FLEET_TURNAROUND_HOURS = 48
DEFAULT_GRACE_DAYS = 10
ROLL_SERVICE_FEE_CENTS = Decimal("2.0")
REPLACEMENT_ADMIN_FEE_USD = Decimal("250.00")

POSTURE_RESTRICTED_AT = Decimal("0.8000")
POSTURE_FROZEN_AT = Decimal("1.0000")

SERVICE_FEE_TIER_1_CEILING_USD = Decimal("50000.00")
SERVICE_FEE_TIER_2_CEILING_USD = Decimal("250000.00")
SERVICE_FEE_TIER_1_CENTS = Decimal("3.0")
SERVICE_FEE_TIER_2_CENTS = Decimal("2.0")
SERVICE_FEE_TIER_3_CENTS = Decimal("1.0")

FACTOR_ORDER = ("MOISTURE", "TEST_WEIGHT", "FOREIGN_MATERIAL", "DAMAGE")
FACTOR_FIELD = {
    "MOISTURE": "moisture_pct",
    "TEST_WEIGHT": "test_weight_lbs",
    "FOREIGN_MATERIAL": "foreign_material_pct",
    "DAMAGE": "damage_pct",
}


def side_sign(side):
    return Decimal(-1) if side == "SHORT" else Decimal(1)


# --------------------------------------------------------------------------
# delivery_net_bushels
# --------------------------------------------------------------------------
def net_bushels_for(settlement_basis, gross_bushels, moisture_pct, schedule):
    gross = D(gross_bushels)
    if settlement_basis == "SHRINK_FIRST":
        excess = D(moisture_pct) - D(schedule["moisture_standard_pct"])
        if excess < 0:
            excess = Decimal(0)
        shrink_pct = excess * D(schedule["shrink_factor_pct_per_point"])
        net = r2(gross * (Decimal(1) - shrink_pct / Decimal(100)))
    else:
        shrink_pct = Decimal(0)
        net = r2(gross)
    return shrink_pct, net


# --------------------------------------------------------------------------
# quality_discount_total
# --------------------------------------------------------------------------
def quality_discount_total(settlement_basis, measurements, schedule, net_bushels):
    tiers = {t["factor"]: t for t in schedule["tiers"]}
    total = Decimal("0.00")
    for factor in FACTOR_ORDER:
        tier = tiers.get(factor)
        if factor == "MOISTURE" and settlement_basis == "SHRINK_FIRST":
            rate = Decimal(0)
        elif tier is None:
            rate = Decimal(0)
        else:
            measured = D(measurements[FACTOR_FIELD[factor]])
            threshold = D(tier["threshold_value"])
            if tier["direction"] == "ABOVE":
                shortfall = measured - threshold
            else:
                shortfall = threshold - measured
            if shortfall < 0:
                shortfall = Decimal(0)
            steps = ceil_div(shortfall, D(tier["unit_step"]))
            rate = D(steps) * D(tier["rate_cents_per_bushel_per_step"])
        # Extend and round EACH factor to cents, then sum the rounded amounts.
        total = total + r2(D(net_bushels) * rate / Decimal(100))
    return total


# --------------------------------------------------------------------------
# ticket_settlement_value
# --------------------------------------------------------------------------
def service_fee_tier(gross_contract_value_usd):
    if gross_contract_value_usd < SERVICE_FEE_TIER_1_CEILING_USD:
        return SERVICE_FEE_TIER_1_CENTS
    if gross_contract_value_usd < SERVICE_FEE_TIER_2_CEILING_USD:
        return SERVICE_FEE_TIER_2_CENTS
    return SERVICE_FEE_TIER_3_CENTS


def settlement_figures(gross_unit_price_cents, net_bushels, discount_total_usd):
    if gross_unit_price_cents is None:
        return None, None, None, None
    gross_value = r2(D(net_bushels) * D(gross_unit_price_cents) / Decimal(100))
    fee = service_fee_tier(gross_value)
    net_unit_price = D(gross_unit_price_cents) - fee
    settlement = r2(D(net_bushels) * net_unit_price / Decimal(100)) \
        - D(discount_total_usd)
    return gross_value, fee, net_unit_price, settlement


# --------------------------------------------------------------------------
# contract_hedge_lots
# --------------------------------------------------------------------------
def hedge_lots_for(bushels):
    return r0(D(bushels) / CONTRACT_UNIT_BUSHELS)


# --------------------------------------------------------------------------
# mark_to_market_equity
# --------------------------------------------------------------------------
def mark_to_market(position, settlement_price_cents):
    sign = side_sign(position["side"])
    unrealized = r2(sign * (D(settlement_price_cents)
                            - D(position["avg_entry_price_cents"]))
                    * D(position["lots_open"]) * CONTRACT_UNIT_BUSHELS
                    / Decimal(100))
    equity = r2(D(position["posted_margin_usd"]) + unrealized)
    maintenance = r2(D(position["lots_open"])
                     * MAINTENANCE_MARGIN_USD_PER_LOT[position["commodity_code"]])
    return unrealized, equity, maintenance, equity < maintenance


def margin_call_amount(position, equity_usd):
    initial = r2(D(position["lots_open"])
                 * INITIAL_MARGIN_USD_PER_LOT[position["commodity_code"]])
    gap = initial - D(equity_usd)
    if gap < 0:
        gap = Decimal(0)
    return r2(gap)


def realized_on_close(position, settlement_price_cents, lots):
    sign = side_sign(position["side"])
    return r2(sign * (D(settlement_price_cents)
                      - D(position["avg_entry_price_cents"]))
              * D(lots) * CONTRACT_UNIT_BUSHELS / Decimal(100))


def weighted_average(pairs):
    """pairs: iterable of (price, quantity). Returns (vwap 4dp, total qty)."""
    total_qty = Decimal(0)
    total_value = Decimal(0)
    for price, qty in pairs:
        total_qty += D(qty)
        total_value += D(price) * D(qty)
    if total_qty == 0:
        return None, Decimal(0)
    return r4(total_value / total_qty), total_qty
