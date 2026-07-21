"""Calculation rules (§1.3). All monetary quantities are integer cents."""
from decimal import Decimal, ROUND_HALF_UP

# Commission ladder
TIER_WIDTH = 100_000_000            # $1,000,000 in cents
MIN_COMMISSION_CENTS = 1_500_000    # $15,000 floor
_TIERS = [(TIER_WIDTH, "0.05"), (TIER_WIDTH, "0.04"),
          (TIER_WIDTH, "0.03"), (TIER_WIDTH, "0.02")]
_FLAT_RATE = "0.01"

# Qualification
DOWN_PAYMENT_PCT = Decimal("0.10")
NET_WORTH_MULTIPLE = Decimal("2.0")
SBA_MAX_CENTS = 500_000_000

# Settlement waterfall
ESCROW_FEE_PCT = Decimal("0.01")

# Earnout
CAP_RATIO = Decimal("1.5")


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cim_recommended_price(listing, valuation_method):
    if valuation_method == "SDE_MULTIPLE":
        mult = Decimal(str(listing["industry_multiple"]))
        return round_half_up(Decimal(listing["annual_sde_cents"]) * mult)
    else:  # ASSET_BASED
        return int(listing["ffe_value_cents"]) + int(listing["inventory_value_cents"])


def broker_commission(base_price_cents):
    base = Decimal(base_price_cents)
    remaining = base
    commission = Decimal(0)
    for width, rate in _TIERS:
        take = min(remaining, Decimal(width))
        commission += take * Decimal(rate)
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        commission += remaining * Decimal(_FLAT_RATE)
    commission = round_half_up(commission)
    return max(commission, MIN_COMMISSION_CENTS)


def required_down_payment(asking_price_cents):
    return round_half_up(DOWN_PAYMENT_PCT * Decimal(asking_price_cents))


def qualification_capacity(proof_of_funds_cents, net_worth_cents):
    leverage = round_half_up(Decimal(proof_of_funds_cents) / DOWN_PAYMENT_PCT)
    net_worth_ceiling = round_half_up(Decimal(net_worth_cents) * NET_WORTH_MULTIPLE)
    return min(leverage, net_worth_ceiling, SBA_MAX_CENTS)


def escrow_fee(closing_price_cents):
    return round_half_up(ESCROW_FEE_PCT * Decimal(closing_price_cents))


def seller_net_proceeds(closing_price_cents, final_commission_cents, earnout_total_cents):
    fee = escrow_fee(closing_price_cents)
    return (int(closing_price_cents)
            - int(final_commission_cents)
            - fee
            - int(earnout_total_cents))


def earnout_period_payment(actual_sde_cents, baseline_sde_cents,
                           earnout_total_cents, earnout_periods):
    if baseline_sde_cents and baseline_sde_cents > 0:
        ratio = Decimal(actual_sde_cents) / Decimal(baseline_sde_cents)
    else:
        ratio = Decimal(0)
    if ratio < 0:
        ratio = Decimal(0)
    if ratio > CAP_RATIO:
        ratio = CAP_RATIO
    if earnout_periods and earnout_periods > 0:
        return round_half_up(Decimal(earnout_total_cents) * ratio / Decimal(earnout_periods))
    return 0
