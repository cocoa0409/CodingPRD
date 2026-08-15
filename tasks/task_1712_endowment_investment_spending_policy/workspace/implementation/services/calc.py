# Calculation rules: unit prices, manager returns (Modified Dietz + simple),
# excess streaks, redemption units, underwater flag, allocation drift inputs.
from constants import INCEPTION_UNIT_PRICE_MILLICENTS, QUARTER_DAYS
from util import rhu


def preliminary_price(estimated_mv_cents, total_units_outstanding_micro):
    """Price at valuation creation. Inception price when no units exist."""
    if total_units_outstanding_micro == 0:
        return INCEPTION_UNIT_PRICE_MILLICENTS
    return max(1, rhu(estimated_mv_cents * 1000000000, total_units_outstanding_micro))


def final_price(final_mv_cents, units_pre_flow_micro):
    """Price at finalize, from pre-flow units. Floored at 1 millicent."""
    if units_pre_flow_micro == 0:
        return INCEPTION_UNIT_PRICE_MILLICENTS
    return max(1, rhu(final_mv_cents * 1000000000, units_pre_flow_micro))


def units_for_amount(amount_cents, price_millicents):
    """Micro-units bought or burned for a cash amount at a price."""
    return rhu(amount_cents * 1000000000, price_millicents)


def fund_market_value(units_held_micro, price_millicents):
    return rhu(units_held_micro * price_millicents, 1000000000)


def rhu_pct(class_mv_cents, total_mv_cents):
    """actual_pct_bps = round_half_up(class_mv * 10000 / total_mv)."""
    return rhu(class_mv_cents * 10000, total_mv_cents)


def compute_manager_returns(beginning_mv, ending_mv, flows, benchmark_bps):
    """Modified Dietz (official) + flow-blind simple comparator + excess."""
    sum_f = sum(f["amount_cents"] for f in flows)
    dietz_denominator = beginning_mv * QUARTER_DAYS + sum(
        (QUARTER_DAYS - f["day_offset"]) * f["amount_cents"] for f in flows
    )
    if dietz_denominator == 0:
        return_bps = 0
    else:
        return_bps = rhu(
            10000 * (ending_mv - beginning_mv - sum_f) * QUARTER_DAYS,
            dietz_denominator,
        )
    if beginning_mv == 0:
        simple_return_bps = 0
    else:
        simple_return_bps = rhu(
            10000 * (ending_mv - beginning_mv - sum_f), beginning_mv
        )
    excess_bps = return_bps - benchmark_bps
    return return_bps, simple_return_bps, excess_bps


def apply_excess_streak(manager, excess_bps):
    """Streak bookkeeping + exact-threshold auto-transitions (evaluated
    immediately after the streak update)."""
    changed = False
    if excess_bps < 0:
        manager["neg_excess_streak"] += 1
        manager["nonneg_excess_streak"] = 0
    else:
        manager["nonneg_excess_streak"] += 1
        manager["neg_excess_streak"] = 0
    status = manager["engagement_status"]
    if status == "ENGAGED" and manager["neg_excess_streak"] == 3:
        manager["engagement_status"] = "WATCHLIST"
        changed = True
    elif status == "WATCHLIST" and manager["neg_excess_streak"] == 6:
        manager["engagement_status"] = "PROBATION"
        changed = True
    elif status == "WATCHLIST" and manager["nonneg_excess_streak"] == 2:
        manager["engagement_status"] = "ENGAGED"
        changed = True
    elif status == "PROBATION" and manager["nonneg_excess_streak"] == 2:
        manager["engagement_status"] = "WATCHLIST"
        changed = True
    return changed
