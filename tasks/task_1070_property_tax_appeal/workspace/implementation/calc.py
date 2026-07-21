"""Precision-sensitive calculations for the Property-Tax Appeal API.

All money is integer cents. Every fractional-cent result is rounded half up
(away from zero) to the nearest whole cent per PRD §2.5. Ratios/rates take part
in intermediate arithmetic at full Decimal precision; rounding is applied only
where a rule explicitly names a rounding step.
"""

from decimal import Decimal, ROUND_HALF_UP


def D(x):
    return Decimal(str(x))


def rhu(x):
    """Round a Decimal to a whole integer, half up (away from zero)."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def median_cents(vals):
    """Median of a list of integer cents. Odd -> middle; even -> round_half_up
    of the mean of the two middle values."""
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return rhu((D(s[mid - 1]) + D(s[mid])) / D(2))


def adjusted_sale_value(sale_price_cents, adjustment_pct):
    return rhu(D(sale_price_cents) * (Decimal(1) + D(adjustment_pct)))


def opinion_of_value(method, included_evidence, equalization_ratio):
    """included_evidence: list of evidence dicts (order irrelevant to median).
    Per-comp figure is rounded BEFORE the median is taken."""
    if method == "SALES_COMPARISON":
        vals = [e["adjusted_sale_value_cents"] for e in included_evidence]
    else:  # ASSESSMENT_EQUITY
        vals = [rhu(D(e["comp_assessed_value_cents"]) / D(equalization_ratio))
                for e in included_evidence]
    return median_cents(vals)


def tax_savings(base_cents, result_cents, millage_rate):
    return rhu((D(base_cents) - D(result_cents)) * D(millage_rate) / D(1000))


def contingency_fee(savings_cents, fa):
    """Marginal, tiered contingency fee. Sum the three bands in exact
    arithmetic, round once, then floor at minimum_fee_cents when savings > 0.
    No fee (0) when savings is not positive."""
    if savings_cents <= 0:
        return 0
    t1c = fa["tier1_ceiling_cents"]
    t2c = fa["tier2_ceiling_cents"]
    band1 = min(savings_cents, t1c)
    band2 = max(0, min(savings_cents - t1c, t2c - t1c))
    band3 = max(0, savings_cents - t2c)
    raw = (D(band1) * D(fa["contingency_tier1_pct"])
           + D(band2) * D(fa["contingency_tier2_pct"])
           + D(band3) * D(fa["contingency_tier3_pct"]))
    fee = rhu(raw)
    return max(fa["minimum_fee_cents"], fee)


def projected_annual_tax(assessed_value_cents, total_exemption_cents, millage_rate):
    base = max(assessed_value_cents - total_exemption_cents, 0)
    return rhu(D(base) * D(millage_rate) / D(1000))


def projected_client_tax_bill(requested_value_cents, total_exemption_cents, millage_rate):
    return rhu((D(requested_value_cents) - D(total_exemption_cents)) * D(millage_rate) / D(1000))
