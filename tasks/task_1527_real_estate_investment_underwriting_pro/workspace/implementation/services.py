"""Business logic: calculations, state machines, cascades."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, getcontext

from db import DB, new_id, now_iso, now_dt
from errors import ApiError
from util import round_half_up_int, touch

getcontext().prec = 50


# ---------------------------------------------------------------------------
# Helpers — finders
# ---------------------------------------------------------------------------

def deal_properties(deal_id):
    return [p for p in DB["properties"].values() if p["deal_id"] == deal_id]


def deal_assumptions(deal_id):
    return [m for m in DB["market_assumptions"].values() if m["deal_id"] == deal_id]


def deal_scenarios(deal_id):
    return [s for s in DB["scenarios"].values() if s["deal_id"] == deal_id]


def deal_memos(deal_id):
    return [m for m in DB["ic_memos"].values() if m["deal_id"] == deal_id]


def memo_votes(memo_id):
    return [v for v in DB["ic_votes"].values() if v["memo_id"] == memo_id]


def scenario_debt_sizings(scenario_id):
    return [d for d in DB["debt_sizings"].values() if d["scenario_id"] == scenario_id]


def scenario_waterfalls(scenario_id):
    return [w for w in DB["waterfalls"].values() if w["scenario_id"] == scenario_id]


def latest_rent_roll(prop_id):
    """Most recent RentRollPeriod on the property by period_month; None if none."""
    rows = [r for r in DB["rent_roll_periods"].values() if r["property_id"] == prop_id]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["period_month"], r["created_at"]))
    return rows[-1]


def latest_year_expenses(prop_id):
    """All OperatingExpense rows on the property for the LATEST period_year, summed; None if none."""
    rows = [o for o in DB["operating_expenses"].values() if o["property_id"] == prop_id]
    if not rows:
        return None, None
    latest_year = max(o["period_year"] for o in rows)
    summed = sum(o["amount_cents"] for o in rows if o["period_year"] == latest_year)
    return latest_year, summed


# ---------------------------------------------------------------------------
# Occupancy cascade (Property)
# ---------------------------------------------------------------------------

def recompute_occupancy(prop):
    """occupancy_pct = round_half_up(occupied/total*10000)/100, 2 decimals; null until first roll."""
    rr = latest_rent_roll(prop["id"])
    if rr is None:
        prop["occupancy_pct"] = None
        return
    ratio_scaled = (Decimal(rr["occupied_units"]) / Decimal(rr["total_units"])) * Decimal(10000)
    rounded = ratio_scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    pct = rounded / Decimal(100)  # 2 decimal places
    # Store as float with exactly 2 decimals for JSON serialization (e.g. 92.5 for 92.50)
    prop["occupancy_pct"] = float(pct)


# ---------------------------------------------------------------------------
# Calculations: NOI, IRR, Equity Multiple
# ---------------------------------------------------------------------------

def compute_noi_yr1(scenario, deal, prop, assumption, variant="provisional"):
    """Compute Year-1 NOI per PRD 3.4.1.

    variant: "provisional" (concessions netted AFTER growth) or
             "final" (concessions netted BEFORE growth)
    Returns integer cents, round-half-up.
    """
    rr = latest_rent_roll(prop["id"])
    if rr is None:
        # No rent roll yet: no income side. Should not be reachable in practice for compute.
        raise ApiError("ERR_INVALID_STATE", 409, "Property has no rent roll; cannot compute NOI")
    _yr, opex_sum = latest_year_expenses(prop["id"])
    if opex_sum is None:
        opex_sum = 0

    gpr_annual = Decimal(rr["gross_potential_rent_cents"]) * Decimal(12)
    concessions_annual = Decimal(rr["concessions_cents"]) * Decimal(12)
    occ_factor = Decimal(scenario["occupancy_stress_pct"]) / Decimal(100)
    growth_yr1 = Decimal(1) + Decimal(assumption["market_rent_growth_yr1_bps"]) / Decimal(10000)

    if variant == "final":
        base_egi = (gpr_annual - concessions_annual) * occ_factor * growth_yr1
    else:  # provisional
        base_egi = gpr_annual * occ_factor * growth_yr1 - concessions_annual

    exp_growth = Decimal(1) + Decimal(assumption["expense_growth_bps"]) / Decimal(10000)
    opex_yr1 = Decimal(opex_sum) * exp_growth
    capex = Decimal(assumption["capex_per_unit_cents"]) * Decimal(prop["units"]) / Decimal(
        max(1, assumption["hold_period_years"])
    )
    lease_up = (
        Decimal(assumption["lease_up_months"])
        * Decimal(rr["gross_potential_rent_cents"])
        * (Decimal(1) - occ_factor)
    )
    opex_yr1 = opex_yr1 + capex + lease_up

    noi = base_egi - opex_yr1
    return round_half_up_int(noi)


def project_noi_series(noi1_cents, steady_growth_bps, hold_years):
    """Return list of Decimal NOIs for years 1..hold_years (index 0 is year 1)."""
    factor = Decimal(1) + Decimal(steady_growth_bps) / Decimal(10000)
    series = []
    base = Decimal(noi1_cents)
    for t in range(1, hold_years + 1):
        series.append(base * (factor ** Decimal(t - 1)))
    return series


def compute_exit_value(noi1_cents, steady_growth_bps, hold_years, exit_cap_bps):
    """Exit value = (noi1 * (1+g)^hold) / exit_cap, round-half-up integer cents."""
    factor = Decimal(1) + Decimal(steady_growth_bps) / Decimal(10000)
    noi_terminal = Decimal(noi1_cents) * (factor ** Decimal(hold_years))
    exit_cap = Decimal(exit_cap_bps) / Decimal(10000)
    if exit_cap <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "exit_cap_rate_bps must be > 0")
    exit_value = noi_terminal / exit_cap
    return round_half_up_int(exit_value)


def compute_irr_bps(price_cents, noi_series, exit_value_cents):
    """Unlevered IRR via bisection on r in [-0.99, 1.00], tol 1e-6. Returns integer bps, half-up."""
    hold = len(noi_series)

    def npv(r):
        r_dec = Decimal(str(r))
        total = -Decimal(price_cents)
        for t in range(1, hold + 1):
            cf = noi_series[t - 1]
            if t == hold:
                cf = cf + Decimal(exit_value_cents)
            denom = (Decimal(1) + r_dec) ** Decimal(t)
            total = total + cf / denom
        return total

    lo, hi = -0.99, 1.00
    f_lo = npv(lo)
    f_hi = npv(hi)
    # If both same sign, IRR not bracketed — clamp to nearest bound
    if f_lo == 0:
        irr = lo
    elif f_hi == 0:
        irr = hi
    elif (f_lo > 0) == (f_hi > 0):
        # No sign change: return closest bound
        irr = lo if abs(f_lo) < abs(f_hi) else hi
    else:
        for _ in range(200):
            mid = (lo + hi) / 2
            f_mid = npv(mid)
            if abs(f_mid) < Decimal("1e-6"):
                irr = mid
                break
            if (f_lo > 0) == (f_mid > 0):
                lo, f_lo = mid, f_mid
            else:
                hi = mid
            if (hi - lo) < 1e-6:
                irr = (lo + hi) / 2
                break
        else:
            irr = (lo + hi) / 2
    irr_bps = Decimal(str(irr)) * Decimal(10000)
    return round_half_up_int(irr_bps)


def compute_equity_multiple_bp(price_cents, noi_series, exit_value_cents):
    """Equity multiple in basis points: total_distributions / invested * 10000, half-up."""
    total = sum(noi_series) + Decimal(exit_value_cents)
    invested = Decimal(price_cents)
    if invested <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "target_purchase_price_cents must be > 0 for compute")
    multiple_bp = (total / invested) * Decimal(10000)
    return round_half_up_int(multiple_bp)


# ---------------------------------------------------------------------------
# Debt sizing
# ---------------------------------------------------------------------------

def size_debt(scenario, deal, interest_rate_bps, amortization_years, io_months, min_dscr_pct, max_ltv_pct):
    """Per PRD 3.5. Returns dict with loan_amount_cents, dscr_at_size_pct, ltv_at_size_pct, sizing_constraint."""
    noi = scenario["computed_noi_yr1_cents"]
    if noi is None or noi <= 0:
        raise ApiError("ERR_NOI_NONPOSITIVE", 422, "computed_noi_yr1_cents must be > 0 for debt sizing")

    rate = Decimal(interest_rate_bps) / Decimal(10000)
    n = amortization_years * 12
    monthly_rate = rate / Decimal(12)
    if monthly_rate == 0:
        annual_ds_per_dollar = Decimal(1) / Decimal(amortization_years)
    else:
        one_plus = Decimal(1) + monthly_rate
        neg_n_power = one_plus ** Decimal(-n)
        denom = Decimal(1) - neg_n_power
        pmt_per_dollar = monthly_rate / denom
        annual_ds_per_dollar = pmt_per_dollar * Decimal(12)

    min_dscr = Decimal(min_dscr_pct) / Decimal(100)
    max_ltv = Decimal(max_ltv_pct) / Decimal(100)
    price = Decimal(deal["target_purchase_price_cents"])

    dscr_max = Decimal(noi) / (min_dscr * annual_ds_per_dollar)
    ltv_max = price * max_ltv

    loan_dec = min(dscr_max, ltv_max)
    # floor to integer cents
    loan_amount = int(loan_dec.quantize(Decimal("1"), rounding=ROUND_FLOOR))

    diff = abs(dscr_max - ltv_max)
    if diff < Decimal(1):
        constraint = "BOTH"
    elif dscr_max < ltv_max:
        constraint = "DSCR"
    else:
        constraint = "LTV"

    # dscr_at_size: noi / (loan * annual_ds_per_dollar) as decimal -> whole percent (nearest)
    if loan_amount > 0:
        dscr_at_size_decimal = Decimal(noi) / (Decimal(loan_amount) * annual_ds_per_dollar)
        dscr_pct_decimal = dscr_at_size_decimal * Decimal(100)
    else:
        dscr_pct_decimal = Decimal(0)
    dscr_at_size_pct = int(dscr_pct_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # ltv_at_size: loan / price * 100 -> nearest whole percent
    if price > 0:
        ltv_pct_decimal = (Decimal(loan_amount) / price) * Decimal(100)
    else:
        ltv_pct_decimal = Decimal(0)
    ltv_at_size_pct = int(ltv_pct_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return {
        "loan_amount_cents": loan_amount,
        "dscr_at_size_pct": dscr_at_size_pct,
        "ltv_at_size_pct": ltv_at_size_pct,
        "sizing_constraint": constraint,
    }


# ---------------------------------------------------------------------------
# Waterfall
# ---------------------------------------------------------------------------

def run_waterfall(scenario, deal, assumption, pref_return_bps, promote_tier1_bps, tier1_hurdle_bps, promote_tier2_bps):
    """Per PRD 3.6. Returns dict with lp_split_cents, gp_split_cents, gp_promote_cents."""
    noi1 = scenario["computed_noi_yr1_cents"]
    if noi1 is None:
        raise ApiError("ERR_INVALID_STATE", 409, "Scenario has not been computed")
    hold = assumption["hold_period_years"]
    series = project_noi_series(noi1, assumption["market_rent_growth_steady_bps"], hold)
    exit_value = compute_exit_value(
        noi1, assumption["market_rent_growth_steady_bps"], hold, assumption["exit_cap_rate_bps"]
    )
    total_distributions = sum(series) + Decimal(exit_value)

    price = Decimal(deal["target_purchase_price_cents"])
    lp_equity = price * Decimal("0.90")
    gp_equity = price - lp_equity

    # Tier 1: LP preferred return (simple, not compounded)
    pref_owed = lp_equity * (Decimal(pref_return_bps) / Decimal(10000)) * Decimal(hold)
    profit_after_capital = total_distributions - (lp_equity + gp_equity)
    lp_pref = min(pref_owed, max(Decimal(0), profit_after_capital))
    lp_pref = Decimal(round_half_up_int(lp_pref))

    remaining = profit_after_capital - lp_pref

    # Tier 2: tier-1 excess up to hurdle
    hurdle_amount = (
        lp_equity * ((Decimal(1) + Decimal(tier1_hurdle_bps) / Decimal(10000)) ** Decimal(hold) - Decimal(1))
        - lp_pref
    )
    tier1_excess = min(max(Decimal(0), remaining), max(Decimal(0), hurdle_amount))
    tier1_excess = Decimal(round_half_up_int(tier1_excess))
    gp_tier1 = tier1_excess * Decimal(promote_tier1_bps) / Decimal(10000)
    gp_tier1 = Decimal(round_half_up_int(gp_tier1))
    lp_tier1 = tier1_excess - gp_tier1

    # Tier 3: tier-2 excess above hurdle
    tier2_excess = remaining - tier1_excess
    gp_tier2 = tier2_excess * Decimal(promote_tier2_bps) / Decimal(10000)
    gp_tier2 = Decimal(round_half_up_int(gp_tier2))
    lp_tier2 = tier2_excess - gp_tier2

    lp_split = lp_equity + lp_pref + lp_tier1 + lp_tier2
    gp_split = gp_equity + gp_tier1 + gp_tier2
    gp_promote = gp_tier1 + gp_tier2

    return {
        "lp_split_cents": round_half_up_int(lp_split),
        "gp_split_cents": round_half_up_int(gp_split),
        "gp_promote_cents": round_half_up_int(gp_promote),
    }


# ---------------------------------------------------------------------------
# Scenario compute
# ---------------------------------------------------------------------------

def compute_scenario(scenario):
    """Run noi_year1 (provisional), irr_unlevered, equity_multiple. Writes results onto scenario."""
    deal = DB["deals"][scenario["deal_id"]]
    assumption = DB["market_assumptions"][scenario["assumption_id"]]
    props = deal_properties(deal["id"])
    if not props:
        raise ApiError("ERR_INVALID_STATE", 409, "Deal has no property; cannot compute scenario")
    prop = props[0]

    noi1 = compute_noi_yr1(scenario, deal, prop, assumption, variant="provisional")
    hold = assumption["hold_period_years"]
    series = project_noi_series(noi1, assumption["market_rent_growth_steady_bps"], hold)
    exit_value = compute_exit_value(
        noi1, assumption["market_rent_growth_steady_bps"], hold, assumption["exit_cap_rate_bps"]
    )
    irr_bps = compute_irr_bps(deal["target_purchase_price_cents"], series, exit_value)
    eq_mult_bp = compute_equity_multiple_bp(deal["target_purchase_price_cents"], series, exit_value)

    scenario["computed_noi_yr1_cents"] = noi1
    scenario["computed_irr_bps"] = irr_bps
    scenario["computed_equity_multiple_bp"] = eq_mult_bp
    scenario["status"] = "COMPUTED"
    touch(scenario)


# ---------------------------------------------------------------------------
# Deal state machine helpers
# ---------------------------------------------------------------------------

def supersede_other_computed_scenarios(deal_id, pinned_scenario_id, superseded_by_id):
    """Cascade every OTHER COMPUTED scenario on the deal to SUPERSEDED with superseded_by_id."""
    for s in DB["scenarios"].values():
        if (
            s["deal_id"] == deal_id
            and s["id"] != pinned_scenario_id
            and s["status"] == "COMPUTED"
        ):
            s["status"] = "SUPERSEDED"
            s["superseded_by_id"] = superseded_by_id
            touch(s)


def supersede_all_computed_scenarios(deal_id):
    """Cascade ALL COMPUTED scenarios on the deal to SUPERSEDED with superseded_by_id = null."""
    for s in DB["scenarios"].values():
        if s["deal_id"] == deal_id and s["status"] == "COMPUTED":
            s["status"] = "SUPERSEDED"
            s["superseded_by_id"] = None
            touch(s)


def recompute_final_noi_if_pinned(scenario):
    """Recompute scenario.computed_noi_yr1_cents using the FINAL variant when the scenario
    is pinned by an IC memo in IC_REVIEW. Also recomputes dependent IRR and equity multiple
    to keep derived values consistent with the new NOI."""
    deal = DB["deals"][scenario["deal_id"]]
    assumption = DB["market_assumptions"][scenario["assumption_id"]]
    props = deal_properties(deal["id"])
    if not props:
        return
    prop = props[0]
    noi1 = compute_noi_yr1(scenario, deal, prop, assumption, variant="final")
    hold = assumption["hold_period_years"]
    series = project_noi_series(noi1, assumption["market_rent_growth_steady_bps"], hold)
    exit_value = compute_exit_value(
        noi1, assumption["market_rent_growth_steady_bps"], hold, assumption["exit_cap_rate_bps"]
    )
    irr_bps = compute_irr_bps(deal["target_purchase_price_cents"], series, exit_value)
    eq_mult_bp = compute_equity_multiple_bp(deal["target_purchase_price_cents"], series, exit_value)
    scenario["computed_noi_yr1_cents"] = noi1
    scenario["computed_irr_bps"] = irr_bps
    scenario["computed_equity_multiple_bp"] = eq_mult_bp
    # Note: scenario.version is not bumped here; recompute replaces the provisional value
    # without a state transition.
