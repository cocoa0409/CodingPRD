"""Pure calculations of PRD §3 — no writes happen in this module."""

from datetime import timedelta

from db import db, ordered
from util import (
    BPS_SCALE,
    ceil_div,
    floor_div,
    fy_first_day,
    fy_last_day,
    month_span,
    parse_date_str,
    parse_dt,
    rhu,
)

TIER_FACTORS_BPS = [2500, 5000, 7500, 10000]
SHORTFALL_TRIGGER_BPS = 150
METHODOLOGY_FLAG_BPS = 500
WINDOW_YEARS = 3
BRIEFING_BLACKOUT_HOURS = 48
VOTE_WINDOW_DAYS = 7


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def active_sources():
    return [s for s in ordered(db.sources) if s["status"] == "ACTIVE"]


def all_sources():
    return ordered(db.sources)


def scenarios_of(cycle_id):
    return [s for s in ordered(db.scenarios) if s["cycle_id"] == cycle_id]


def adjustments_of(source_id):
    return [a for a in ordered(db.adjustments) if a["source_id"] == source_id]


def items_of(cycle_id, source_id=None, active_only=True):
    out = []
    for it in ordered(db.items):
        if it["cycle_id"] != cycle_id:
            continue
        if source_id is not None and it["source_id"] != source_id:
            continue
        if active_only and it["status"] != "ACTIVE":
            continue
        out.append(it)
    return out


def rounds_of(cycle_id):
    return [r for r in ordered(db.rounds) if r["cycle_id"] == cycle_id]


def estimates_of(round_id):
    return [e for e in ordered(db.estimates) if e["round_id"] == round_id]


def estimate_for(round_id, source_id, body):
    for e in ordered(db.estimates):
        if e["round_id"] == round_id and e["source_id"] == source_id and e["body"] == body:
            return e
    return None


def disagreements_of(round_id, source_id=None):
    out = []
    for d in ordered(db.disagreements):
        if d["round_id"] != round_id:
            continue
        if source_id is not None and d["source_id"] != source_id:
            continue
        out.append(d)
    return out


def transactions_of(fund_id):
    return [t for t in ordered(db.transactions) if t["fund_id"] == fund_id]


def votes_of(request_id):
    return [v for v in ordered(db.votes) if v["request_id"] == request_id]


def briefings_of_fund(fund_id):
    return [b for b in ordered(db.briefings) if b["fund_id"] == fund_id]


def briefings_of_cycle(cycle_id):
    return [b for b in ordered(db.briefings) if b["cycle_id"] == cycle_id]


def actuals_of_source(source_id):
    return [a for a in ordered(db.actuals) if a["source_id"] == source_id]


# --------------------------------------------------------------------------
# §3.4 weighted_scenario_source_estimate — STEP ORDER IS NORMATIVE
# --------------------------------------------------------------------------
def weighted_scenario_cents(cycle, source):
    weighted_sum = 0
    for s in scenarios_of(cycle["id"]):
        driver_sum = (
            s["employment_growth_bps"] * source["elasticity_employment_bps"]
            + s["wage_income_bps"] * source["elasticity_wage_income_bps"]
            + s["retail_sales_bps"] * source["elasticity_retail_bps"]
            + s["asset_market_return_bps"] * source["elasticity_asset_bps"]
        )
        growth_bps = rhu(driver_sum, BPS_SCALE)                                   # STEP 1
        amount = rhu(source["base_year_receipts_cents"] * (BPS_SCALE + growth_bps),
                     BPS_SCALE)                                                   # STEP 2
        weighted_sum += amount * s["weight_bps"]
    return rhu(weighted_sum, BPS_SCALE)                                           # STEP 3


# --------------------------------------------------------------------------
# §3.2 policy_change_phase_in_amount
# --------------------------------------------------------------------------
def adjustment_contribution(adj, fiscal_year):
    if adj["first_effective_fiscal_year"] > fiscal_year:
        return 0
    fy_start = fy_first_day(fiscal_year)
    fy_end = fy_last_day(fiscal_year)
    start = parse_date_str(adj["effective_start_date"])
    end = parse_date_str(adj["effective_end_date"]) if adj.get("effective_end_date") else None
    if start > fy_end:
        return 0
    if end is not None and end <= fy_start:
        return 0

    kind = adj["phase_in_type"]
    if kind == "FULL":
        raw = adj["annualized_amount_cents"]
    elif kind == "PRORATED":
        overlap_start = max(start, fy_start)
        last_covered = (end - timedelta(days=1)) if end is not None else fy_end
        overlap_end = min(last_covered, fy_end)
        months = month_span(overlap_start, overlap_end)
        raw = rhu(adj["annualized_amount_cents"] * months, 12)
    else:  # TIERED
        tier_index = fiscal_year - adj["first_effective_fiscal_year"]
        if tier_index < 0:
            tier_index = 0
        factor = TIER_FACTORS_BPS[min(tier_index, 3)]
        raw = rhu(adj["annualized_amount_cents"] * factor, BPS_SCALE)

    cap = adj["cap_amount_cents"]
    capped = raw if cap == 0 else min(raw, cap)
    return capped if adj["adjustment_kind"] == "INCREASE" else -capped


def policy_adjustment_cents(source, fiscal_year):
    total = 0
    for adj in adjustments_of(source["id"]):
        total += adjustment_contribution(adj, fiscal_year)
    return total


def one_time_cents(cycle_id, source_id):
    return sum(it["amount_cents"] for it in items_of(cycle_id, source_id))


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; a null end means open-ended."""
    if a_end is not None and a_end <= b_start:
        return False
    if b_end is not None and b_end <= a_start:
        return False
    return True


# --------------------------------------------------------------------------
# §3.4 consensus_variance
# --------------------------------------------------------------------------
def variance_figures(rnd):
    """(per_source_bps, exec_total, leg_total, variance_bps) for a round."""
    per_source = {}
    for src in active_sources():
        e = estimate_for(rnd["id"], src["id"], "EXECUTIVE")
        l = estimate_for(rnd["id"], src["id"], "LEGISLATIVE")
        if e is None or l is None:
            continue
        ev = e["estimate_amount_cents"]
        lv = l["estimate_amount_cents"]
        midpoint = rhu(ev + lv, 2)
        per_source[src["id"]] = 0 if midpoint == 0 else rhu(abs(ev - lv) * BPS_SCALE, midpoint)

    exec_total = sum(e["estimate_amount_cents"] for e in estimates_of(rnd["id"])
                     if e["body"] == "EXECUTIVE")
    leg_total = sum(e["estimate_amount_cents"] for e in estimates_of(rnd["id"])
                    if e["body"] == "LEGISLATIVE")
    grand_midpoint = rhu(exec_total + leg_total, 2)
    variance_bps = 0 if grand_midpoint == 0 else rhu(abs(exec_total - leg_total) * BPS_SCALE,
                                                     grand_midpoint)
    return per_source, exec_total, leg_total, variance_bps


# --------------------------------------------------------------------------
# §3.5 consensus_reconciled_total
# --------------------------------------------------------------------------
def resolved_record(round_id, source_id):
    for d in disagreements_of(round_id, source_id):
        if d["status"] == "RESOLVED":
            return d
    return None


def reconciled_for_source(rnd, source_id):
    """The round's per-source reconciled contribution, or None when unavailable."""
    record = resolved_record(rnd["id"], source_id)
    if record is not None:
        return record["resolved_amount_cents"]
    e = estimate_for(rnd["id"], source_id, "EXECUTIVE")
    l = estimate_for(rnd["id"], source_id, "LEGISLATIVE")
    if e is None or l is None:
        return None
    cycle = db.cycles.get(rnd["cycle_id"])
    ev = e["estimate_amount_cents"]
    lv = l["estimate_amount_cents"]
    if cycle and cycle["reconciliation_policy"] == "LOWER_OF_TWO":
        return min(ev, lv)                      # no rounding at all
    return rhu(ev + lv, 2)


def reconciled_total_cents(rnd):
    total = 0
    for src in active_sources():
        value = reconciled_for_source(rnd, src["id"])
        if value is not None:
            total += value
    return total


# --------------------------------------------------------------------------
# §3.6 shortfall_trigger
# --------------------------------------------------------------------------
def shortfall_figures(enacted, certified_total):
    gap = enacted - certified_total
    if gap < 0:
        gap = 0
    pct = 0 if enacted == 0 else floor_div(gap * BPS_SCALE, enacted)
    return gap, pct


# --------------------------------------------------------------------------
# §3.7 reserve_adequacy
# --------------------------------------------------------------------------
def reference_cycle():
    """CERTIFIED cycle with the greatest certified_at, ties by earliest created_at."""
    best = None
    for cyc in ordered(db.cycles):
        if cyc["status"] != "CERTIFIED" or not cyc.get("certified_at"):
            continue
        if best is None:
            best = cyc
            continue
        cur = parse_dt(cyc["certified_at"])
        top = parse_dt(best["certified_at"])
        if cur > top:
            best = cyc
        # equal certified_at: `ordered` already walks created_at ascending, so the
        # incumbent is the earlier-created cycle and wins the tie.
    return best


def volatility_index_bps():
    numerator = 0
    denominator = 0
    for src in active_sources():
        numerator += src["mape_bps"] * src["base_year_receipts_cents"]
        denominator += src["base_year_receipts_cents"]
    if denominator == 0:
        return 0
    return rhu(numerator, denominator)


def target_pct_for(vi):
    if vi <= 300:
        return 500
    if vi <= 800:
        return 800
    return 1200


def band_for(coverage):
    if coverage >= 10000:
        return "STRONG"
    if coverage >= 6000:
        return "ADEQUATE"
    if coverage >= 3000:
        return "THIN"
    return "INSUFFICIENT"


def adequacy_figures(fund, ref=None):
    """The eight-step disclosure of §3.7. Returns a plain dict; persists nothing."""
    if ref is None:
        ref = reference_cycle()
    vi = volatility_index_bps()                                        # STEP 1
    target = target_pct_for(vi)                                        # STEP 2
    if ref is not None and ref.get("certified_recurring_total_cents") is not None:
        required = rhu(ref["certified_recurring_total_cents"] * target, BPS_SCALE)  # STEP 3
    else:
        required = None
    balance = fund["balance_cents"]
    if required is None or required == 0:
        coverage = 0                                                   # STEP 4 (floor)
    else:
        coverage = floor_div(balance * BPS_SCALE, required)
    band = band_for(coverage)                                          # STEP 5
    cushion = 200 if band == "STRONG" else 0                           # STEP 6
    disclosed = target - cushion                                       # STEP 7
    if ref is not None and ref.get("certified_total_cents") is not None:
        cap = rhu(ref["certified_total_cents"] * fund["cap_pct_bps"], BPS_SCALE)    # STEP 8
    else:
        cap = None
    return {
        "reference_cycle_id": ref["id"] if ref is not None else None,
        "volatility_index_bps": vi,
        "target_pct_bps": target,
        "required_reserve_cents": required,
        "coverage_ratio_bps": coverage,
        "adequacy_band": band,
        "cushion_credit_bps": cushion,
        "disclosed_target_pct_bps": disclosed,
        "cap_cents": cap,
    }


def deposit_headroom(fund, cap_cents=None):
    cap = fund["cap_cents"] if cap_cents is None else cap_cents
    if cap is None:
        return None
    return max(0, cap - fund["balance_cents"])


# --------------------------------------------------------------------------
# §3.6 reserve_deposit_amount
# --------------------------------------------------------------------------
def deposit_computation(cycle, fund, ratified_round):
    if fund["deposit_rule_variant"] == "GROWTH_ABOVE_TREND":
        measured = cycle["certified_recurring_total_cents"]
        trend_line = rhu(cycle["prior_recurring_baseline_cents"]
                         * (BPS_SCALE + fund["trend_growth_rate_bps"]), BPS_SCALE)
    else:  # VOLATILE_SOURCE_CAPTURE
        measured = 0
        base_sum = 0
        for src in active_sources():
            if src["volatility_class"] != "HIGH":
                continue
            reconciled = reconciled_for_source(ratified_round, src["id"]) if ratified_round else None
            if reconciled is None:
                reconciled = 0
            measured += reconciled - one_time_cents(cycle["id"], src["id"])
            base_sum += src["base_year_receipts_cents"]
        trend_line = rhu(base_sum * (BPS_SCALE + fund["trend_growth_rate_bps"]), BPS_SCALE)

    excess = max(0, measured - trend_line)
    gross = rhu(excess * fund["capture_rate_bps"], BPS_SCALE)
    cap_cents = rhu(cycle["certified_total_cents"] * fund["cap_pct_bps"], BPS_SCALE)
    headroom = max(0, cap_cents - fund["balance_cents"])
    deposited = min(gross, headroom)
    return {
        "measured_cents": measured,
        "trend_line_cents": trend_line,
        "excess_cents": excess,
        "gross_computed_cents": gross,
        "cap_cents": cap_cents,
        "headroom_cents": headroom,
        "deposited_cents": deposited,
        "overflow_returned_cents": gross - deposited,
    }


# --------------------------------------------------------------------------
# §3.8 withdrawal_authorization
# --------------------------------------------------------------------------
def votes_required_for(seats):
    return ceil_div(seats * 2, 3)


def quorum_required_for(seats):
    return ceil_div(seats, 2)


def annual_withdrawal_cap_cents(fund):
    return rhu(fund["fy_opening_balance_cents"] * fund["annual_withdrawal_cap_pct_bps"],
               BPS_SCALE)


def cap_headroom_cents(fund):
    return max(0, annual_withdrawal_cap_cents(fund) - fund["fy_withdrawn_cents"])


# --------------------------------------------------------------------------
# §3.9 forecast_error_metrics
# --------------------------------------------------------------------------
def matched_cycle_for(fiscal_year):
    """Greatest certified_at among CERTIFIED/SUPERSEDED cycles of that fiscal year."""
    best = None
    for cyc in ordered(db.cycles):
        if cyc["fiscal_year"] != fiscal_year:
            continue
        if cyc["status"] not in ("CERTIFIED", "SUPERSEDED"):
            continue
        if not cyc.get("certified_at"):
            continue
        if best is None or parse_dt(cyc["certified_at"]) > parse_dt(best["certified_at"]):
            best = cyc
    return best


def error_window(source_id):
    rows = actuals_of_source(source_id)
    rows = [r for r in rows if r.get("abs_pct_error_bps") is not None]
    rows.sort(key=lambda r: (-r["fiscal_year"], r["_seq"]))
    return rows[:WINDOW_YEARS]


def mape_for(source_id):
    window = error_window(source_id)
    if not window:
        return 0
    return rhu(sum(r["abs_pct_error_bps"] for r in window), len(window))
