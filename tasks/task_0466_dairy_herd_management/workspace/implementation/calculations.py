"""The six calculation rules (SCAFFOLD §1.3 / PRD §3).

All rounding is round-half-up. The pinned discipline throughout: round each
line first, then sum the rounded lines.
"""
from util import round1, round2

# Constants (SCAFFOLD §1.3)
STANDARD_LACTATION_DAYS = 305
OTHER_SOLIDS_PCT = 5.7
SCC_BASE_THOUSANDS = 350
SCC_RATE_PER_1000_PER_CWT = 0.0005
SCC_GOOD_MAX = 200
SCC_WARNING_MAX = 400
PREG_CHECK_WINDOW_DAYS = 45
VWP_DAYS = 30


# ---------------------------------------------------------------------------
# 1. daily_feed_cost
# ---------------------------------------------------------------------------
def daily_feed_cost(ingredients):
    """SUM over ingredients of round2(lbs_as_fed * price_per_lb).

    Per-line rounding to the cent, THEN sum the rounded line costs.
    """
    total = 0.0
    for ing in ingredients:
        line = round2(ing["lbs_as_fed"] * ing["price_per_lb"])
        total += line
    # Sum of already-rounded cents stays at 2dp; round defensively.
    return round2(total)


# ---------------------------------------------------------------------------
# 2. lactation_cumulative_milk (Test-Interval Method)
# ---------------------------------------------------------------------------
def lactation_cumulative_milk(tests):
    """tests: list of (day_in_milk, milk_weight_lbs) sorted by day_in_milk ASC.

    cumulative = w_0 * dim_0
    for i in 1..n-1: cumulative += ((w_{i-1}+w_i)/2) * (dim_i - dim_{i-1})
    round1 at the end.
    """
    if not tests:
        return 0.0
    dim0, w0 = tests[0]
    cumulative = w0 * dim0
    for i in range(1, len(tests)):
        dim_prev, w_prev = tests[i - 1]
        dim_i, w_i = tests[i]
        cumulative += ((w_prev + w_i) / 2.0) * (dim_i - dim_prev)
    return round1(cumulative)


# ---------------------------------------------------------------------------
# 3. lactation_projected_305d
# ---------------------------------------------------------------------------
def lactation_projected_305d(tests, cumulative_milk_lbs):
    """tests sorted by day_in_milk ASC; cumulative is the already-computed value.

    No test -> 0.
    last_dim >= 305 -> projected = cumulative.
    else -> round1(cumulative + last_w * (305 - last_dim)).
    """
    if not tests:
        return 0.0
    last_dim, last_w = tests[-1]
    if last_dim >= STANDARD_LACTATION_DAYS:
        return cumulative_milk_lbs
    projected = cumulative_milk_lbs + last_w * (STANDARD_LACTATION_DAYS - last_dim)
    return round1(projected)


# ---------------------------------------------------------------------------
# 4. milk_check_settlement
# ---------------------------------------------------------------------------
def provisional_advance(pooled_milk_lbs, advance_rate_per_cwt):
    """advance_paid = round2(advance_rate_per_cwt * pooled_milk_lbs / 100)."""
    return round2(advance_rate_per_cwt * pooled_milk_lbs / 100.0)


def pool_components(pooled_records):
    """Compute pooled totals from the list of test-day record dicts.

    Returns a dict with pooled_milk_lbs, pooled_fat_lbs, pooled_protein_lbs,
    pooled_other_solids_lbs, weighted_scc_thousands.
    Per-record component pounds are round2'd, then summed.
    """
    pooled_milk = 0.0
    pooled_fat = 0.0
    pooled_protein = 0.0
    pooled_ops = 0.0
    scc_weight_sum = 0.0
    for r in pooled_records:
        mw = r["milk_weight_lbs"]
        pooled_milk += mw
        pooled_fat += round2(mw * r["fat_pct"] / 100.0)
        pooled_protein += round2(mw * r["protein_pct"] / 100.0)
        pooled_ops += round2(mw * OTHER_SOLIDS_PCT / 100.0)
        scc_weight_sum += r["scc_thousands"] * mw
    if pooled_milk > 0:
        weighted_scc = round2(scc_weight_sum / pooled_milk)
    else:
        weighted_scc = 0.0
    return {
        "pooled_milk_lbs": pooled_milk,
        "pooled_fat_lbs": round2(pooled_fat),
        "pooled_protein_lbs": round2(pooled_protein),
        "pooled_other_solids_lbs": round2(pooled_ops),
        "weighted_scc_thousands": weighted_scc,
    }


def final_settlement(pool, price_sheet, advance_paid):
    """Compute gross_settlement, hauling_deduction, net_payable.

    Five dollar lines each round2'd, then summed for gross_settlement.
    net_payable = gross - advance_paid - hauling (exact subtraction).
    """
    pooled_milk = pool["pooled_milk_lbs"]
    cwt = pooled_milk / 100.0
    weighted_scc = pool["weighted_scc_thousands"]

    fat_value = round2(pool["pooled_fat_lbs"] * price_sheet["fat_price_per_lb"])
    prot_value = round2(pool["pooled_protein_lbs"] * price_sheet["protein_price_per_lb"])
    ops_value = round2(pool["pooled_other_solids_lbs"] * price_sheet["other_solids_price_per_lb"])
    scc_adj = round2((SCC_BASE_THOUSANDS - weighted_scc) * SCC_RATE_PER_1000_PER_CWT * cwt)
    ppd_value = round2(price_sheet["ppd_per_cwt"] * cwt)

    gross_settlement = round2(fat_value + prot_value + ops_value + scc_adj + ppd_value)
    hauling_deduction = round2(price_sheet["hauling_rate_per_cwt"] * cwt)
    net_payable = gross_settlement - advance_paid - hauling_deduction
    # net_payable is an exact subtraction of already-rounded values; normalize
    # only to clean binary-float noise (no further rounding semantics).
    net_payable = round2(net_payable)
    return {
        "gross_settlement": gross_settlement,
        "hauling_deduction": hauling_deduction,
        "net_payable": net_payable,
    }


# ---------------------------------------------------------------------------
# 5. income_over_feed_cost
# ---------------------------------------------------------------------------
def income_over_feed_cost(latest_test_milk_lbs, blend_price_per_cwt, daily_feed_cost_per_cow):
    milk_revenue = round2(latest_test_milk_lbs / 100.0 * blend_price_per_cwt)
    iofc = milk_revenue - daily_feed_cost_per_cow
    return {
        "milk_revenue": milk_revenue,
        "daily_feed_cost_per_cow": daily_feed_cost_per_cow,
        "iofc_per_cow_per_day": round2(iofc),
    }


# ---------------------------------------------------------------------------
# 6. herd_milk_quality_status
# ---------------------------------------------------------------------------
def herd_milk_quality_status(weighted_scc_thousands):
    if weighted_scc_thousands <= SCC_GOOD_MAX:
        return "GOOD"
    elif weighted_scc_thousands <= SCC_WARNING_MAX:
        return "WARNING"
    return "PENALIZED"
