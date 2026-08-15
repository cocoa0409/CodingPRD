"""Calculation rules of scaffold 1.3 / PRD 3.4-3.7.

Precision discipline (PRD 2.6):
  - interest/expense rounded HALF-UP to integer cents PER POSITION, then summed
  - derived pct outputs (nii_delta_pct, eve_delta_pct, deviation_pct) 2dp HALF-UP
  - hedge offset_ratio 4dp HALF-UP
  - intermediates (ramp-averaged year-one delta, effective cpr/decay, blended
    rates, pass-through fractions) are used UNROUNDED downstream
All arithmetic runs on Decimal; floats never touch money or rates.
"""

from decimal import Decimal, ROUND_HALF_UP

D0 = Decimal("0")
D1 = Decimal("1")
CENT = Decimal("1")
PCT2 = Decimal("0.01")
PCT4 = Decimal("0.0001")
HUNDRED = Decimal("100")
TENK = Decimal("10000")
TWELVE = Decimal("12")

ASSET_CATEGORIES = ("LOAN", "SECURITY")
LIABILITY_CATEGORIES = ("DEPOSIT", "BORROWING")
NONMATURITY_SEGMENTS = ("RETAIL_NONMATURITY", "BUSINESS_NONMATURITY")

# Scaffold 1.3 scenario_year1_rate_delta: preset -> instantaneous shock (bps).
PRESET_SHOCK_BPS = {
    "REG_UP_400": 400,
    "REG_UP_300": 300,
    "REG_UP_200": 200,
    "REG_DOWN_200": -200,
    "REG_DOWN_300": -300,
    "REG_DOWN_400": -400,
}
PRESET_CODES = tuple(PRESET_SHOCK_BPS.keys())

# Scaffold 1.3 backtest_deviation constants.
BACKTEST_TOLERANCE_PCT = {
    "PREPAYMENT": Decimal("3.0"),
    "DEPOSIT_DECAY": Decimal("2.0"),
    "DEPOSIT_BETA": Decimal("10.0"),
}

# Scaffold 1.1 AssumptionSet.params domain schemas (exact key sets).
PARAM_SCHEMA = {
    "PREPAYMENT": frozenset(("base_cpr_pct", "prepay_sensitivity_per_100bps")),
    "DEPOSIT_DECAY": frozenset(("base_annual_decay_pct", "surge_decay_per_100bps")),
    "DEPOSIT_BETA": frozenset(("up_beta_pct", "down_beta_pct", "lag_months")),
}

# Scaffold 1.3 backtest_deviation: predicted value per domain.
PREDICTED_PARAM_KEY = {
    "PREPAYMENT": "base_cpr_pct",
    "DEPOSIT_DECAY": "base_annual_decay_pct",
    "DEPOSIT_BETA": "up_beta_pct",
}


def dec(value):
    """JSON number -> Decimal via its shortest repr (no float artifacts)."""
    return Decimal(str(value))


def round_cents(value):
    """round_half_up to integer cents."""
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


def round_pct2(value):
    """round_half_up to exactly two decimal places."""
    return value.quantize(PCT2, rounding=ROUND_HALF_UP)


def round_ratio4(value):
    """round_half_up to exactly four decimal places."""
    return value.quantize(PCT4, rounding=ROUND_HALF_UP)


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# scenario_year1_rate_delta
# ---------------------------------------------------------------------------

def rate_deltas(scenario):
    """Return (delta_y1_bps, terminal_shock_bps), both Decimal and unrounded.

    PARALLEL_SHOCK / REGULATORY_PRESET: delta_y1 = the effective shock.
    RAMP: linear 0 -> ramp_total_bps over ramp_months; average over the first
      twelve months is pinned as
        ramp_months <= 12: ramp_total_bps * (12 - ramp_months/2) / 12
        ramp_months >  12: ramp_total_bps * 6 / ramp_months
    EVE always uses the terminal shock: the effective shock, or ramp_total_bps
    for a RAMP.
    """
    kind = scenario["kind"]
    if kind == "PARALLEL_SHOCK":
        shock = dec(scenario["shock_bps"])
        return shock, shock
    if kind == "REGULATORY_PRESET":
        shock = Decimal(PRESET_SHOCK_BPS[scenario["preset_code"]])
        return shock, shock
    # RAMP
    total = dec(scenario["ramp_total_bps"])
    months = dec(scenario["ramp_months"])
    if scenario["ramp_months"] <= 12:
        delta_y1 = total * (TWELVE - months / Decimal(2)) / TWELVE
    else:
        delta_y1 = total * Decimal(6) / months
    return delta_y1, total


# ---------------------------------------------------------------------------
# Effective behavioral assumptions
# ---------------------------------------------------------------------------

def effective_cpr_pct(prepay_params, delta_y1):
    """clamp(base + sensitivity * max(0, -delta)/100, 0, 100); rates falling
    speed prepayments up, rising rates never slow them below base."""
    base = dec(prepay_params["base_cpr_pct"])
    sens = dec(prepay_params["prepay_sensitivity_per_100bps"])
    return clamp(base + sens * max(D0, -delta_y1) / HUNDRED, D0, HUNDRED)


def effective_deposit_rate_bps(beta_params, position, delta_y1, scenario_kind):
    """Non-maturity deposits only. beta = up when delta > 0 else down;
    pass-through 1.0 for SHOCK/PRESET, max(0, 12 - lag)/12 for RAMP;
    new rate floored at zero."""
    beta = dec(beta_params["up_beta_pct"]) if delta_y1 > 0 else dec(beta_params["down_beta_pct"])
    if scenario_kind == "RAMP":
        lag = dec(beta_params["lag_months"])
        pass_through = max(D0, TWELVE - lag) / TWELVE
    else:
        pass_through = D1
    rate = dec(position["rate_bps"]) + (beta / HUNDRED) * delta_y1 * pass_through
    return max(D0, rate)


def effective_annual_decay_pct(decay_params, delta_y1):
    """clamp(base + surge * max(0, delta)/100, 0, 100); rising rates accelerate
    runoff, falling rates leave base decay."""
    base = dec(decay_params["base_annual_decay_pct"])
    surge = dec(decay_params["surge_decay_per_100bps"])
    return clamp(base + surge * max(D0, delta_y1) / HUNDRED, D0, HUNDRED)


# ---------------------------------------------------------------------------
# nii_projection (STATIC / DYNAMIC variants)
# ---------------------------------------------------------------------------

def nii_projection_cents(book, active_positions, delta_y1, scenario_kind,
                         prepay_params, decay_params, beta_params,
                         convention, annual_growth_pct):
    """Net interest income in integer cents. Rounding order is pinned: each
    position's interest/expense is rounded half-up to integer cents FIRST,
    then summed."""
    new_money_bps = max(D0, dec(book["base_curve_rate_bps"]) + delta_y1)
    dynamic = convention == "DYNAMIC"
    growth_factor = (D1 + dec(annual_growth_pct) / HUNDRED) if dynamic else None

    interest_total = 0
    expense_total = 0
    for pos in active_positions:
        balance = dec(pos["balance_cents"])
        rate = dec(pos["rate_bps"])
        runoff = dec(pos["scheduled_runoff_pct"])
        category = pos["category"]

        if category in ASSET_CATEGORIES:
            runoff_eff = runoff
            if category == "LOAN" and pos.get("is_prepayment_eligible"):
                runoff_eff = runoff + effective_cpr_pct(prepay_params, delta_y1)
            blended = (D1 - runoff_eff / HUNDRED) * rate + (runoff_eff / HUNDRED) * new_money_bps
            balance_used = balance * growth_factor if dynamic else balance
            interest_total += round_cents(balance_used * blended / TENK)
        elif category == "DEPOSIT" and pos.get("deposit_segment") in NONMATURITY_SEGMENTS:
            rate_used = effective_deposit_rate_bps(beta_params, pos, delta_y1, scenario_kind)
            if dynamic:
                # decay first, then growth (order pinned by PRD 3.4)
                decay_pct = effective_annual_decay_pct(decay_params, delta_y1)
                balance_used = balance * (D1 - decay_pct / HUNDRED) * growth_factor
            else:
                balance_used = balance
            expense_total += round_cents(balance_used * rate_used / TENK)
        else:
            # TIME deposits and BORROWING reprice via scheduled runoff.
            blended = (D1 - runoff / HUNDRED) * rate + (runoff / HUNDRED) * new_money_bps
            balance_used = balance * growth_factor if dynamic else balance
            expense_total += round_cents(balance_used * blended / TENK)

    return interest_total - expense_total


def nii_delta_pct(nii_base_cents, nii_scenario_cents):
    """2dp HALF-UP; 0.00 when the base is exactly zero."""
    if nii_base_cents == 0:
        return Decimal("0.00")
    return round_pct2(
        (Decimal(nii_scenario_cents) - Decimal(nii_base_cents))
        / Decimal(nii_base_cents) * HUNDRED
    )


# ---------------------------------------------------------------------------
# eve_duration_approximation
# ---------------------------------------------------------------------------

def eve_projection(book, active_positions, terminal_shock_bps):
    """Return (eve_base_cents, eve_scenario_cents, eve_delta_pct).

    DA/DL are balance-weighted average durations over ACTIVE assets /
    liabilities; empty sides contribute zero duration. eve_base = TA - TL;
    eve_scenario = round_half_up(eve_base - (DA*TA - DL*TL) * shock / 10000);
    delta pct is 0.00 when eve_base <= 0.
    """
    assets = [p for p in active_positions if p["category"] in ASSET_CATEGORIES]
    liabilities = [p for p in active_positions if p["category"] in LIABILITY_CATEGORIES]
    ta = sum(p["balance_cents"] for p in assets)
    tl = sum(p["balance_cents"] for p in liabilities)
    if ta:
        da = sum(dec(p["balance_cents"]) * dec(p["duration_years"]) for p in assets) / dec(ta)
    else:
        da = D0
    if tl:
        dl = sum(dec(p["balance_cents"]) * dec(p["duration_years"]) for p in liabilities) / dec(tl)
    else:
        dl = D0
    eve_base = ta - tl
    gap = da * dec(ta) - dl * dec(tl)
    eve_scenario = round_cents(dec(eve_base) - gap * terminal_shock_bps / TENK)
    if eve_base <= 0:
        pct = Decimal("0.00")
    else:
        pct = round_pct2(
            (Decimal(eve_scenario) - Decimal(eve_base)) / Decimal(eve_base) * HUNDRED
        )
    return eve_base, eve_scenario, pct


# ---------------------------------------------------------------------------
# policy_limit_evaluation (comparison on the rounded 2dp delta values)
# ---------------------------------------------------------------------------

def limit_applies(limit, scenario_kind):
    """applies_to_kinds is ALL (bare string or list containing it) or a list
    of scenario kinds."""
    kinds = limit["applies_to_kinds"]
    if kinds == "ALL":
        return True
    if isinstance(kinds, list) and "ALL" in kinds:
        return True
    return scenario_kind in kinds


def limit_is_breached(limit, nii_delta, eve_delta):
    """Breach iff delta_pct < -threshold_pct (strict); exactly at the negative
    threshold is NOT a breach."""
    threshold = dec(limit["threshold_pct"])
    if limit["metric"] == "NII_DELTA_PCT":
        return nii_delta < -threshold
    return eve_delta < -threshold


# ---------------------------------------------------------------------------
# hedge_effectiveness_result
# ---------------------------------------------------------------------------

def effectiveness_result(method, hedge_change, hedged_change, slope, r_squared, sample_count):
    """Return (result, offset_ratio).

    DOLLAR_OFFSET: hedged change == 0 fails outright (ratio unset); otherwise
      offset_ratio = round_half_up_4dp(-(hedge/hedged)), PASS iff
      0.8000 <= ratio <= 1.2500 inclusive both ends.
    REGRESSION: PASS iff r_squared >= 0.80 AND 0.80 <= slope <= 1.25 AND
      sample_count >= 12. Each method ignores the other's inputs.
    """
    if method == "DOLLAR_OFFSET":
        if hedged_change == 0:
            return "FAIL", None
        ratio = round_ratio4(-(dec(hedge_change) / dec(hedged_change)))
        ok = Decimal("0.8000") <= ratio <= Decimal("1.2500")
        return ("PASS" if ok else "FAIL"), float(ratio)
    # REGRESSION
    if slope is None or r_squared is None or sample_count is None:
        return "FAIL", None
    ok = (
        dec(r_squared) >= Decimal("0.80")
        and Decimal("0.80") <= dec(slope) <= Decimal("1.25")
        and sample_count >= 12
    )
    return ("PASS" if ok else "FAIL"), None


# ---------------------------------------------------------------------------
# backtest_deviation
# ---------------------------------------------------------------------------

def backtest_outcome(domain, predicted_value_pct, observed_value_pct):
    """Return (deviation_pct, outcome). deviation = round_half_up_2dp(
    abs(observed - predicted)); BREACH iff deviation > tolerance (strict;
    equality is WITHIN_TOLERANCE)."""
    deviation = round_pct2(abs(dec(observed_value_pct) - dec(predicted_value_pct)))
    tolerance = BACKTEST_TOLERANCE_PCT[domain]
    outcome = "BREACH" if deviation > tolerance else "WITHIN_TOLERANCE"
    return deviation, outcome
