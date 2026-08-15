"""Tax gross-up calculation per scaffold `tax_gross_up`.

FLAT_SUPPLEMENTAL: gross_up = round_half_up(net * rate / (1 - rate))
MARGINAL_AGGREGATE: split net against marginal_bracket_threshold_cents given the
case's cumulative_taxable_paid_cents, gross each portion up at its own rate, then sum.
"""

from decimal import Decimal, ROUND_HALF_UP


def _gross_portion(net_cents, rate):
    """portion_gross_up = round_half_up(net * rate / (1 - rate))."""
    if net_cents <= 0:
        return 0
    net = Decimal(int(net_cents))
    r = Decimal(str(rate))
    denom = Decimal(1) - r
    if denom <= 0:
        # degenerate rate >= 1: gross-up is mathematically undefined; treat as zero
        return 0
    gross_up = net * r / denom
    return int(gross_up.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_gross_up(claim, case, policy):
    """Return gross_up_cents for a PAID transition. 0 when claim is not taxable."""
    if not claim.get("taxable"):
        return 0
    net = claim["amount_cents"]
    method = policy["gross_up_method"]
    if method == "FLAT_SUPPLEMENTAL":
        return _gross_portion(net, policy["flat_gross_up_rate"])
    # MARGINAL_AGGREGATE
    C = case.get("cumulative_taxable_paid_cents", 0)
    T = policy["marginal_bracket_threshold_cents"]
    below = max(0, min(net, T - C))
    above = net - below
    return _gross_portion(below, policy["marginal_rate_low"]) + _gross_portion(
        above, policy["marginal_rate_high"]
    )
