"""Dual-variant pricing engine (PRD §3.4, SCAFFOLD §1.3 calculations).

Money is integer cents via Decimal + ROUND_HALF_UP. Weight reductions (shrink)
use floor. Discounts stack multiplicatively: bulk discount applies only to the
grams at/above bulk_threshold_g, on top of the tier discount.

PRD §2.6: pricing rounds half-up at the per-line level, then sums lines.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

G_PER_KG = 1000
HOLIDAY_DEPOSIT_RATE = Decimal("0.25")


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, ties up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _tier_pct(loyalty_tier, policy):
    if loyalty_tier == "PREFERRED":
        return Decimal(str(policy["preferred_discount_pct"]))
    if loyalty_tier == "WHOLESALE":
        return Decimal(str(policy["wholesale_discount_pct"]))
    return Decimal(0)  # STANDARD


def _price_grams(grams, cut, policy, loyalty_tier):
    """Shared tiered-pricing body operating on a whole-number gram count.

    Splits grams around bulk_threshold_g (inclusive at threshold), applies the
    tier discount to all grams and an extra multiplicative bulk discount to the
    bulk portion, then rounds half-up to whole cents.
    """
    base_per_g = Decimal(str(cut["base_price_cents_per_kg"])) / Decimal(G_PER_KG)
    tier_pct = _tier_pct(loyalty_tier, policy)
    bulk_threshold = policy["bulk_threshold_g"]
    bulk_extra = Decimal(str(policy["bulk_extra_discount_pct"]))

    grams_d = Decimal(grams)
    if grams >= bulk_threshold:
        bulk_g = Decimal(grams - bulk_threshold)
        normal_g = grams_d - bulk_g
        normal_part = normal_g * base_per_g * (Decimal(1) - tier_pct)
        bulk_part = (bulk_g * base_per_g * (Decimal(1) - tier_pct)
                     * (Decimal(1) - bulk_extra))
        total = normal_part + bulk_part
    else:
        total = grams_d * base_per_g * (Decimal(1) - tier_pct)
    return round_half_up(total)


def estimated_line_cents(ordered_weight_g, cut, policy, loyalty_tier):
    """ESTIMATE variant (PRD §3.4): ordered_weight_g, no shrink."""
    return _price_grams(ordered_weight_g, cut, policy, loyalty_tier)


def final_line_cents(catch_weight_g, cut, policy, loyalty_tier):
    """FINAL variant (PRD §3.4): catch_weight_g reduced by shrink (floor) first."""
    if cut["is_grind"]:
        shrink = Decimal(str(policy["shrink_pct_grind"]))
    else:
        shrink = Decimal(str(policy["shrink_pct_whole_cut"]))
    billable_g = int(math.floor(catch_weight_g * (Decimal(1) - shrink)))
    return _price_grams(billable_g, cut, policy, loyalty_tier)


def holiday_deposit_cents(estimated_total_cents):
    """PRD §3.6: HOLIDAY_DEPOSIT_RATE * estimated_total, round half up once."""
    return round_half_up(Decimal(estimated_total_cents) * HOLIDAY_DEPOSIT_RATE)


def sausage_yield_g(total_input_g, policy):
    """PRD §3.8: sum(inputs) * (1 - shrink_pct_grind), floored."""
    shrink = Decimal(str(policy["shrink_pct_grind"]))
    return int(math.floor(total_input_g * (Decimal(1) - shrink)))
