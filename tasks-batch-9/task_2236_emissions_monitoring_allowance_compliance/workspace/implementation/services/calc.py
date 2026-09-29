"""The eleven calculations of PRD section 3, expressed as pure functions.

Every one of them works in ``Decimal`` and finishes through
:func:`util.rhu` (round half away from zero) at the precision PRD 2.6 pins:

1.  calibration error percentages + verdict ladder      (3.2)
2.  CEMS hourly heat input / SO2 / NOx / CO2            (3.5)
3.  Appendix D hourly heat input / SO2 / NOx / CO2      (3.5)
4.  monitor data availability percentage                (3.6)
5.  missing-data substitution tier ladder + lookback    (3.6)
6.  quarterly report roll-ups                           (3.7)
7.  RATA run statistics (means, sd, cc)                 (3.3)
8.  relative accuracy + bias adjustment factor          (3.3)
9.  rolling permit-limit window value                   (3.8)
10. exceedance magnitude / pct / penalty allowance debit (3.8)
11. true-up obligation waterfall                        (3.9)  -- see allowances.py
"""

from decimal import Decimal

from constants import (
    APPENDIX_D_CO2_FACTOR,
    APPENDIX_D_SO2_FACTOR,
    AVAILABILITY_FLOOR,
    CEMS_HEAT_INPUT_DIVISOR,
    CO2_CEMS_FACTOR,
    LBS_PER_TON,
    LOOKBACK_SIZE,
    MAX_POTENTIAL_CONCENTRATION_PPM,
    MMBTU_PER_MILLION_BTU,
    PERCENTILE_90,
    PERCENTILE_95,
    RATA_PASS_THRESHOLD,
    SO2_CEMS_FACTOR,
    T_VALUES,
    TIER1_AVAILABILITY,
    TIER2_AVAILABILITY,
    TIER3_AVAILABILITY,
    WINDOW_MIN_SAMPLES,
    WINDOW_SPAN_HOURS,
)
from db import db
from util import D, ceil_int, hours_before, quarter_of, rhu, rhu_dec, sample_stdev

HUNDRED = Decimal(100)


# ---------------------------------------------------------------------------
# 1. daily calibration
# ---------------------------------------------------------------------------

def calibration_percentages(zero_ref, zero_meas, span_ref, span_meas, span_value):
    """Both errors are expressed as a percentage of span, two decimals."""
    zero_err = rhu(abs(D(zero_meas) - D(zero_ref)) / D(span_value) * HUNDRED, 2)
    span_err = rhu(abs(D(span_meas) - D(span_ref)) / D(span_value) * HUNDRED, 2)
    return zero_err, span_err


def calibration_verdict(zero_err, span_err, spec_pct, prior_consecutive_failures):
    """Three-rung ladder (PRD 3.2). Boundaries are strict ``>`` on both rungs:
    exactly twice the spec is *not* an immediate out-of-control, and exactly the
    spec passes.
    """
    worst = max(D(zero_err), D(span_err))
    spec = D(spec_pct)
    if worst > spec * Decimal(2):
        return "OUT_OF_CONTROL_TRIGGERED"
    if worst > spec:
        if prior_consecutive_failures + 1 >= 2:
            return "OUT_OF_CONTROL_TRIGGERED"
        return "FAILED"
    return "PASSED"


# ---------------------------------------------------------------------------
# 2/3. hourly emissions
# ---------------------------------------------------------------------------

def cems_hour_values(flow_scfh, co2_conc_pct, so2_conc_ppm, nox_rate, op_time_fraction, bias_factor):
    flow = D(flow_scfh)
    opf = D(op_time_fraction)
    heat_input = rhu(flow * (D(co2_conc_pct) / HUNDRED) / CEMS_HEAT_INPUT_DIVISOR * opf, 3)
    so2 = None
    if so2_conc_ppm is not None:
        so2 = rhu(SO2_CEMS_FACTOR * D(so2_conc_ppm) * flow * opf * D(bias_factor), 1)
    nox = None
    if nox_rate is not None:
        nox = rhu(D(nox_rate) * D(heat_input), 1)
    co2_tons = rhu(CO2_CEMS_FACTOR * (D(co2_conc_pct) / HUNDRED) * flow * opf / LBS_PER_TON, 3)
    return heat_input, so2, nox, co2_tons


def appendix_d_hour_values(fuel_flow_lbs, gcv_btu_per_lb, sulfur_content_pct, nox_rate, op_time_fraction):
    fuel = D(fuel_flow_lbs)
    opf = D(op_time_fraction)
    heat_input = rhu(fuel * D(gcv_btu_per_lb) / MMBTU_PER_MILLION_BTU * opf, 3)
    # No bias adjustment is ever applied to an Appendix D SO2 mass.
    so2 = rhu(fuel * APPENDIX_D_SO2_FACTOR * (D(sulfur_content_pct) / HUNDRED) * opf, 1)
    nox = None
    if nox_rate is not None:
        nox = rhu(D(nox_rate) * D(heat_input), 1)
    co2_tons = rhu(D(heat_input) * APPENDIX_D_CO2_FACTOR / LBS_PER_TON, 3)
    return heat_input, so2, nox, co2_tons


def substituted_so2_mass(concentration_ppm, flow_scfh, op_time_fraction):
    """Substituted SO2 mass -- the bias adjustment factor is never applied."""
    flow = D(flow_scfh if flow_scfh is not None else 0)
    return rhu(SO2_CEMS_FACTOR * D(concentration_ppm) * flow * D(op_time_fraction), 1)


# ---------------------------------------------------------------------------
# 4. monitor data availability
# ---------------------------------------------------------------------------

def quarter_hours(unit_id, year, quarter):
    rows = []
    for h in db.operating_hours.values():
        if h["unit_id"] != unit_id:
            continue
        hb = h["_hour_begin"]
        if hb.year == year and quarter_of(hb) == quarter:
            rows.append(h)
    return rows


def availability_pct(unit_id, year, quarter, before=None):
    """Denominator: hours of that unit+quarter with ``op_time_fraction > 0``.
    Numerator: those whose ``data_quality`` is MEASURED. Zero-operating hours
    sit in neither. An empty denominator yields 100.0.

    ``before`` (used by substitution) excludes the target hour and every hour at
    or after it.
    """
    rows = quarter_hours(unit_id, year, quarter)
    if before is not None:
        rows = [h for h in rows if h["_hour_begin"] < before]
    denominator = [h for h in rows if D(h["op_time_fraction"]) > 0]
    if not denominator:
        return 100.0
    numerator = [h for h in denominator if h["data_quality"] == "MEASURED"]
    return rhu(D(len(numerator)) / D(len(denominator)) * HUNDRED, 1)


# ---------------------------------------------------------------------------
# 5. missing-data substitution
# ---------------------------------------------------------------------------

def lookback_values(unit_id, target_hour_begin):
    """The 20 most recent MEASURED SO2 concentrations strictly earlier than the
    target, taken hour_begin descending (ties -> earlier created_at first), then
    returned sorted ascending. Count based, so it may cross quarters.
    """
    candidates = []
    for h in db.operating_hours.values():
        if h["unit_id"] != unit_id:
            continue
        if h["data_quality"] != "MEASURED":
            continue
        if h.get("so2_conc_ppm") is None:
            continue
        if h["_hour_begin"] >= target_hour_begin:
            continue
        candidates.append(h)
    candidates.sort(key=lambda h: (h["created_at"], h["_seq"]))
    candidates.sort(key=lambda h: h["_hour_begin"], reverse=True)
    chosen = candidates[:LOOKBACK_SIZE]
    return sorted(D(h["so2_conc_ppm"]) for h in chosen)


def nearest_rank_percentile(sorted_values, quantile):
    """1-based nearest-rank percentile: ``values[ceil(q*n) - 1]``."""
    n = len(sorted_values)
    index = ceil_int(D(quantile) * D(n)) - 1
    if index < 0:
        index = 0
    if index >= n:
        index = n - 1
    return sorted_values[index]


def substitution_tier(availability, lookback):
    """First matching rung wins (PRD 3.6)."""
    if not lookback:
        return "T4_MAX_POTENTIAL_CONCENTRATION", D(MAX_POTENTIAL_CONCENTRATION_PPM)
    avail = D(availability)
    if avail >= TIER1_AVAILABILITY:
        return "T1_90TH_PERCENTILE", nearest_rank_percentile(lookback, PERCENTILE_90)
    if avail >= TIER2_AVAILABILITY:
        return "T2_95TH_PERCENTILE", nearest_rank_percentile(lookback, PERCENTILE_95)
    if avail >= TIER3_AVAILABILITY:
        return "T3_LOOKBACK_MAXIMUM", lookback[-1]
    return "T4_MAX_POTENTIAL_CONCENTRATION", D(MAX_POTENTIAL_CONCENTRATION_PPM)


# ---------------------------------------------------------------------------
# 6. quarterly report roll-ups
# ---------------------------------------------------------------------------

def report_totals(hours):
    """Sum the already-rounded per-hour figures, then round once more at the
    total's own precision. Never re-derive from raw inputs.
    """
    heat = Decimal(0)
    so2 = Decimal(0)
    nox = Decimal(0)
    co2 = Decimal(0)
    for h in hours:
        heat += D(h["heat_input_mmbtu"] if h["heat_input_mmbtu"] is not None else 0)
        so2 += D(h["so2_mass_lbs"] if h["so2_mass_lbs"] is not None else 0)
        nox += D(h["nox_mass_lbs"] if h["nox_mass_lbs"] is not None else 0)
        co2 += D(h["co2_mass_tons"] if h["co2_mass_tons"] is not None else 0)
    total_heat = rhu(heat, 3)
    total_so2_lbs = rhu(so2, 1)
    total_nox = rhu(nox, 1)
    total_co2 = rhu(co2, 3)
    total_so2_tons = rhu(D(total_so2_lbs) / LBS_PER_TON, 3)
    return {
        "total_heat_input_mmbtu": total_heat,
        "total_so2_lbs": total_so2_lbs,
        "total_nox_lbs": total_nox,
        "total_co2_tons": total_co2,
        "total_so2_tons": total_so2_tons,
    }


def report_counts(hours):
    operating = sum(1 for h in hours if D(h["op_time_fraction"]) > 0)
    measured = sum(1 for h in hours if h["data_quality"] == "MEASURED")
    substituted = sum(1 for h in hours if h["data_quality"] == "SUBSTITUTED")
    return operating, measured, substituted


# ---------------------------------------------------------------------------
# 7/8. RATA statistics
# ---------------------------------------------------------------------------

def rata_statistics(runs):
    """``d[i] = reference - cems`` rounded to 4dp; means 4dp; the sample standard
    deviation is carried at 6dp and feeds the confidence coefficient.
    """
    n = len(runs)
    refs = [D(r["reference_value"]) for r in runs]
    cems = [D(r["cems_value"]) for r in runs]
    diffs = [rhu_dec(refs[i] - cems[i], 4) for i in range(n)]
    reference_mean = rhu(sum(refs, Decimal(0)) / D(n), 4)
    cems_mean = rhu(sum(cems, Decimal(0)) / D(n), 4)
    mean_difference = rhu(sum(diffs, Decimal(0)) / D(n), 4)
    sd = rhu_dec(sample_stdev(diffs), 6)
    t_value = T_VALUES[n]
    confidence = rhu(t_value * sd / D(n).sqrt(), 4)
    return {
        "reference_mean": reference_mean,
        "cems_mean": cems_mean,
        "mean_difference": mean_difference,
        "sample_stdev": float(sd),
        "confidence_coefficient": confidence,
    }


def relative_accuracy(mean_difference, confidence_coefficient, denominator):
    numerator = abs(D(mean_difference)) + abs(D(confidence_coefficient))
    return rhu(numerator / D(denominator) * HUNDRED, 1)


def rata_passed(relative_accuracy_pct):
    return D(relative_accuracy_pct) <= RATA_PASS_THRESHOLD


def bias_adjustment(mean_difference, cems_mean):
    """Bias fails when |mean_difference| exceeds |confidence_coefficient|; the
    caller supplies that verdict. Factor = 1 + mean_difference / cems_mean.
    """
    if D(cems_mean) == 0:
        return 1.0
    return rhu(Decimal(1) + D(mean_difference) / D(cems_mean), 4)


# ---------------------------------------------------------------------------
# 9. rolling permit-limit window
# ---------------------------------------------------------------------------

def window_hours(unit_id, averaging_basis, anchor, effective_from):
    span = WINDOW_SPAN_HOURS[averaging_basis]
    earliest = hours_before(anchor, span)
    rows = []
    for h in db.operating_hours.values():
        if h["unit_id"] != unit_id:
            continue
        hb = h["_hour_begin"]
        if hb >= anchor:
            continue
        if hb < earliest:
            continue
        if effective_from is not None and hb < effective_from:
            continue
        if D(h["op_time_fraction"]) <= 0:
            continue
        if h["data_quality"] not in ("MEASURED", "SUBSTITUTED"):
            continue
        rows.append(h)
    rows.sort(key=lambda h: (h["_hour_begin"], h["created_at"], h["_seq"]))
    return rows


def _pollutant_mass(hour, pollutant):
    if pollutant == "SO2":
        value = hour.get("so2_mass_lbs")
        return D(value) if value is not None else Decimal(0)
    if pollutant == "NOX_RATE":
        value = hour.get("nox_mass_lbs")
        return D(value) if value is not None else Decimal(0)
    value = hour.get("co2_mass_tons")
    return (D(value) if value is not None else Decimal(0)) * LBS_PER_TON


def rolling_value(hours, pollutant, limit_units):
    total_mass = sum((_pollutant_mass(h, pollutant) for h in hours), Decimal(0))
    if limit_units == "LB_PER_MMBTU":
        total_heat = sum(
            (D(h["heat_input_mmbtu"]) if h["heat_input_mmbtu"] is not None else Decimal(0))
            for h in hours
        )
        if total_heat == 0:
            return None
        return rhu(total_mass / total_heat, 4)
    if limit_units == "LB_PER_HR":
        return rhu(total_mass / D(len(hours)), 1)
    return rhu(total_mass / LBS_PER_TON, 3)


def sufficient_samples(averaging_basis, count):
    return count >= WINDOW_MIN_SAMPLES[averaging_basis]


# ---------------------------------------------------------------------------
# 10. exceedance figures
# ---------------------------------------------------------------------------

def exceedance_figures(observed_value, limit_value):
    magnitude = rhu(D(observed_value) - D(limit_value), 4)
    pct = rhu(D(magnitude) / D(limit_value) * HUNDRED, 4)
    penalty = max(1, ceil_int(pct))
    return magnitude, pct, penalty


AVAILABILITY_FLOOR_PCT = AVAILABILITY_FLOOR
