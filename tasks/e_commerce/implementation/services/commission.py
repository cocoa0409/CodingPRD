"""Tiered marginal commission calculation."""

from config import COMMISSION_TIERS
from money import round_money


def calculate_commission(shop_monthly_gmv, order_total):
    """Calculate platform commission using marginal tiers.

    Args:
        shop_monthly_gmv: shop's GMV before this order (float)
        order_total: the order total to calculate commission on (float)

    Returns:
        (commission_amount, effective_commission_rate) both rounded to 2dp
        (rate as a proportion, e.g. 0.05 for 5%).
    """
    remaining = order_total
    commission = 0.0
    current_gmv = shop_monthly_gmv

    for tier in COMMISSION_TIERS:
        if remaining <= 0:
            break
        tier_lower = tier["lower"]
        tier_upper = tier["upper"]
        rate = tier["rate"]

        # How much room is left in this tier above current_gmv?
        tier_available = tier_upper - max(tier_lower, current_gmv)
        if tier_available <= 0:
            continue

        taxable = min(remaining, tier_available)
        commission += taxable * rate
        current_gmv += taxable
        remaining -= taxable

    commission = round_money(commission)

    if order_total > 0:
        effective_rate = round_money(commission / order_total)
    else:
        effective_rate = 0.0

    return commission, effective_rate
