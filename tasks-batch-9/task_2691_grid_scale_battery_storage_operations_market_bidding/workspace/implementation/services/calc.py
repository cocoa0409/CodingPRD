"""Pure calculations (PRD 3.3, 3.5, 3.6, 3.8, 3.9).

Every quantity is carried through decimal.Decimal with ROUND_HALF_UP, and the
order in which rounding happens is exactly the order the PRD pins.
"""

from decimal import Decimal

from numeric import D, rnd, f, r2, r3, r4

# --- pinned constants -------------------------------------------------------
CHARGE_ENERGY_COST_USD_PER_MWH = Decimal("22.00")
WARRANTY_ADDER_BASE_USD = Decimal("8.00")
WARRANTY_ADDER_KNEE = Decimal("0.5")
MIN_OFFER_PRICE_USD = Decimal("0.00")

PRODUCT_WEIGHTS = {
    "ENERGY": Decimal("1.00"),
    "REG_UP": Decimal("0.70"),
    "SPIN": Decimal("0.55"),
    "REG_DOWN": Decimal("0.35"),
}

DEADBAND_RATIO = Decimal("0.02")
ACCURACY_WEIGHT = Decimal("0.7")
DEADBAND_WEIGHT = Decimal("0.3")
PERFORMANCE_FLOOR_SCORE = Decimal("75.00")
NON_PERFORMANCE_RATE_USD = Decimal("4.00")

ANNUAL_HOURS = Decimal("8760.0")
AVAILABILITY_TIER1_PCT = Decimal("90.0")
AVAILABILITY_TIER2_PCT = Decimal("80.0")

SAMPLE_INTERVAL_HOURS = Decimal("0.25")
THERMAL_WARNING_TEMP_C = Decimal("65.0")
THERMAL_RUNAWAY_TEMP_C = Decimal("75.0")

THROUGHPUT_FADE_PCT = Decimal("8.0")
CLAIM_TRIGGER_DEFICIT_PCT = Decimal("1.00")
REMEDY_OVERSIZE_FACTOR = Decimal("1.10")
DAYS_PER_YEAR = Decimal("365")


# ---------------------------------------------------------------------------
# 3.3 — the offer price floor
# ---------------------------------------------------------------------------
def cycle_scarcity_multiplier(remaining):
    """Tiered on the asset's remaining annual equivalent-full-cycle budget."""
    remaining = D(remaining)
    if remaining >= Decimal("200"):
        return Decimal("1.00")
    if remaining >= Decimal("100"):
        return Decimal("1.25")
    if remaining >= Decimal("25"):
        return Decimal("1.60")
    return Decimal("2.50")


def offer_price(asset, product, direction, price_adder):
    """Every intermediate term at 4 decimals; only the final price at 2."""
    charge_cost = rnd(CHARGE_ENERGY_COST_USD_PER_MWH * Decimal("100")
                      / D(asset["round_trip_efficiency_pct"]), 4)

    remaining = D(asset["cycle_limit_per_year"]) - D(asset["equivalent_full_cycles_ytd"])
    multiplier = cycle_scarcity_multiplier(remaining)
    degradation = rnd(D(asset["degradation_cost_usd_per_mwh"]) * multiplier, 4)

    ratio = D(asset["cumulative_throughput_mwh"]) / D(asset["warranty_throughput_limit_mwh"])
    excess = ratio - WARRANTY_ADDER_KNEE
    if excess < 0:
        excess = Decimal("0")
    warranty = rnd(WARRANTY_ADDER_BASE_USD * excess * Decimal("2"), 4)

    weight = PRODUCT_WEIGHTS[product]
    if direction == "DISCHARGE":
        base = rnd(charge_cost + degradation + warranty, 4)
    else:
        base = charge_cost - degradation - warranty
        if base < 0:
            base = Decimal("0")
        base = rnd(base, 4)
    floor = rnd(base * weight, 4)

    price = floor + D(price_adder)
    if price < MIN_OFFER_PRICE_USD:
        price = MIN_OFFER_PRICE_USD
    return f(price, 2)


def hours_of(start, end):
    """Interval duration in hours as an exact decimal."""
    seconds = Decimal(str((end - start).total_seconds()))
    return seconds / Decimal("3600")


def expected_energy(mw, start, end):
    return r3(D(mw) * hours_of(start, end))


def cycle_debit(expected_energy_mwh, available_energy_mwh):
    available = D(available_energy_mwh)
    if available <= 0:
        return 0.0
    return r4(D(expected_energy_mwh) / (Decimal("2") * available))


# ---------------------------------------------------------------------------
# 3.5 — per-sample arithmetic
# ---------------------------------------------------------------------------
def sample_apparent_mva(measured_mw, measured_mvar):
    value = (D(measured_mw) ** 2 + D(measured_mvar) ** 2).sqrt()
    return r3(value)


def sample_deviation(measured_mw, instructed_mw):
    diff = D(measured_mw) - D(instructed_mw)
    if diff < 0:
        diff = -diff
    return r3(diff)


def sample_error_ratio(deviation_mw, instructed_mw):
    instructed = D(instructed_mw)
    if instructed <= 0:
        return 0.0
    return r4(D(deviation_mw) / instructed)


def thermal_band(max_cell_temp_c):
    temp = D(max_cell_temp_c)
    if temp >= THERMAL_RUNAWAY_TEMP_C:
        return "RUNAWAY"
    if temp >= THERMAL_WARNING_TEMP_C:
        return "WARNING"
    return "NONE"


def delivered_energy(samples):
    """Sum of measured_mw times the fixed quarter-hour sample width, r3."""
    total = Decimal("0")
    for sample in samples:
        total += D(sample["measured_mw"]) * SAMPLE_INTERVAL_HOURS
    return r3(total)


# ---------------------------------------------------------------------------
# 3.6 — the performance score, shared by both variants
# ---------------------------------------------------------------------------
def performance_score(samples):
    """samples must already be filtered by the variant and ordered by
    sample_index ascending.  Each sample's error_ratio is already rounded to 4
    decimals; the mean of those rounded ratios is deliberately NOT rounded."""
    if not samples:
        return 0.0, 0.0, 0.0
    count = Decimal(len(samples))
    total = Decimal("0")
    in_band = 0
    for sample in samples:
        total += D(sample["error_ratio"])
        if sample["within_deadband"]:
            in_band += 1
    mean = total / count
    accuracy = Decimal("1") - mean
    if accuracy < 0:
        accuracy = Decimal("0")
    accuracy_score = rnd(accuracy * Decimal("100"), 2)
    deadband_pct = rnd(Decimal(in_band) / count * Decimal("100"), 2)
    composite = rnd(ACCURACY_WEIGHT * accuracy_score
                    + DEADBAND_WEIGHT * deadband_pct, 2)
    return f(accuracy_score, 2), f(deadband_pct, 2), f(composite, 2)


def non_performance_charge(composite_score, instructed_mw):
    shortfall = PERFORMANCE_FLOOR_SCORE - D(composite_score)
    if shortfall < 0:
        shortfall = Decimal("0")
    return r2(shortfall * D(instructed_mw) * NON_PERFORMANCE_RATE_USD)


def soc_delta(direction, delivered_mwh, round_trip_efficiency_pct):
    if direction == "DISCHARGE":
        return r3(-D(delivered_mwh))
    return r3(D(delivered_mwh) * D(round_trip_efficiency_pct) / Decimal("100"))


# ---------------------------------------------------------------------------
# 3.8 — capacity obligation assessment (threshold, two variants)
# ---------------------------------------------------------------------------
def availability_multiplier(availability_pct):
    pct = D(availability_pct)
    if pct >= AVAILABILITY_TIER1_PCT:
        return Decimal("1.0")
    if pct >= AVAILABILITY_TIER2_PCT:
        return Decimal("1.5")
    return Decimal("2.0")


def derated_committed(available_energy_mwh, obligation):
    """Non-null only while the plant can no longer sustain committed_mw for
    obligation_duration_hours."""
    duration = D(obligation["obligation_duration_hours"])
    if duration <= 0:
        return None
    sustainable = D(available_energy_mwh) / duration
    if sustainable < D(obligation["committed_mw"]):
        return r3(sustainable)
    return None


def assess_obligation(obligation, mode, period_hours, derated):
    """period_hours is a Decimal; derated is derated_committed_mw or None."""
    period = D(period_hours)
    unavailable = D(obligation["unavailable_hours"])
    measured = rnd(period - unavailable, 2)
    if period <= 0:
        availability_pct = Decimal("0.00")
    else:
        availability_pct = rnd(measured / period * Decimal("100"), 2)

    required = D(obligation["availability_hours_required"])
    if mode == "PRELIMINARY":
        required_scaled = rnd(required * period / ANNUAL_HOURS, 2)
    else:
        required_scaled = required

    shortfall = required_scaled - measured
    if shortfall < 0:
        shortfall = Decimal("0")
    shortfall = rnd(shortfall, 2)

    multiplier = availability_multiplier(availability_pct)
    penalty = rnd(D(obligation["committed_mw"])
                  * D(obligation["penalty_rate_usd_per_mw_hour"])
                  * shortfall * multiplier, 2)

    if shortfall == 0 and mode == "FINAL":
        status = "FULFILLED"
    elif shortfall == 0 and mode == "PRELIMINARY" and derated is None:
        status = "ACTIVE"
    elif shortfall == 0 and derated is not None:
        status = "SHORTFALL"
    elif shortfall > 0 and availability_pct >= AVAILABILITY_TIER1_PCT:
        status = "SHORTFALL"
    else:
        status = "PENALIZED"

    return {
        "measured_available_hours": f(measured, 2),
        "availability_pct": f(availability_pct, 2),
        "shortfall_hours": f(shortfall, 2),
        "penalty_exposure_usd": f(penalty, 2),
        "assessment_mode": mode,
        "derated_committed_mw": derated,
        "status": status,
    }


# ---------------------------------------------------------------------------
# 3.9 — the degradation model (constraint propagation, pinned order)
# ---------------------------------------------------------------------------
def elapsed_years(commercial_operation_date, scheduled_date):
    days = Decimal(str((scheduled_date - commercial_operation_date).total_seconds()
                       / 86400.0))
    return r4(days / DAYS_PER_YEAR)


def expected_soh(asset, years, throughput_before):
    ratio = D(throughput_before) / D(asset["warranty_throughput_limit_mwh"])
    curve = (Decimal("100")
             - D(asset["warranty_annual_fade_pct"]) * D(years)
             - THROUGHPUT_FADE_PCT * ratio * Decimal("100"))
    floor = D(asset["warranty_guaranteed_soh_pct"])
    return r2(floor if floor > curve else curve)


def measured_soh(measured_capacity_mwh, rated_energy_mwh):
    rated = D(rated_energy_mwh)
    if rated <= 0:
        return 0.0
    return r2(D(measured_capacity_mwh) / rated * Decimal("100"))


def soh_deficit(expected_soh_pct, measured_soh_pct):
    diff = D(expected_soh_pct) - D(measured_soh_pct)
    if diff < 0:
        diff = Decimal("0")
    return r2(diff)


def claim_triggered(soh_deficit_pct):
    return D(soh_deficit_pct) >= CLAIM_TRIGGER_DEFICIT_PCT


def remedy_energy(rated_energy_mwh, claimed_shortfall_pct):
    return r3(D(rated_energy_mwh) * D(claimed_shortfall_pct) / Decimal("100")
              * REMEDY_OVERSIZE_FACTOR)
