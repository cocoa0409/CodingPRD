"""All algorithmic rules — PRD §2.6 and §3.

Rounding is round-half-up via decimal.Decimal (never float round / banker's).
Money is not involved here, but numeric precision is contractual.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

MIN_TUR = 4.0
MAX_DEPTH = 10
MIN_POINTS_FOR_LSQ = 2

K1_BY_TRIAL_COUNT = {2: 4.56, 3: 3.05, 4: 2.50}
K2_BY_OPERATOR_COUNT = {2: 3.65, 3: 2.70, 4: 2.30}


def round_half_up(value, places):
    """Round a numeric value to `places` decimals using round-half-up."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return value
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> Decimal('0.01')
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(d)


# ---------------------------------------------------------------------------
# Point pass test (closed interval) — PRD §3.3 / calc cal_result
# ---------------------------------------------------------------------------
def point_pass(value, nominal, tol_minus, tol_plus):
    """True iff nominal - tol_minus <= value <= nominal + tol_plus."""
    return (nominal - tol_minus) <= value <= (nominal + tol_plus)


# ---------------------------------------------------------------------------
# TUR — calc tur_ratio (PRD §3.4)
# ---------------------------------------------------------------------------
def compute_tur(tolerance_plus, tolerance_minus, std_uncertainty):
    """Returns (tur_value, meets_min).

    tolerance_band_width = tolerance_plus + tolerance_minus
    If std_uncertainty == 0: tur infinite, treated as >= MIN_TUR.
    Else tur = band / (2 * uncertainty), rounded 2dp round_half_up.
    """
    band = tolerance_plus + tolerance_minus
    if std_uncertainty == 0:
        return None, True  # infinite — None signals "infinite"; meets minimum
    tur = band / (2.0 * std_uncertainty)
    tur_rounded = round_half_up(tur, 2)
    return tur_rounded, (tur_rounded >= MIN_TUR)


# ---------------------------------------------------------------------------
# Result determination — calc cal_result + tur_ratio downgrade (PRD §3.4)
# ---------------------------------------------------------------------------
def compute_result(as_found_all_pass, as_left_all_pass, tur_meets_min):
    """base outcome with TUR downgrade. Returns one of PASS/CONDITIONAL/FAIL."""
    if as_found_all_pass and as_left_all_pass:
        base = "PASS"
    elif (not as_found_all_pass) and as_left_all_pass:
        base = "CONDITIONAL"
    else:
        base = "FAIL"
    if (not tur_meets_min) and base != "FAIL":
        return "FAIL"
    return base


# ---------------------------------------------------------------------------
# max_abs_deviation — calc drift_deviation (PRD §3.4)
# ---------------------------------------------------------------------------
def max_abs_deviation(points):
    """max over points of abs(as_found_value - nominal), 6dp round_half_up."""
    best = max(abs(p["as_found_value"] - p["nominal"]) for p in points)
    return round_half_up(best, 6)


# ---------------------------------------------------------------------------
# next_due_epoch / last_calibration_epoch — calc next_due_epoch (PRD §3.4)
# ---------------------------------------------------------------------------
def compute_last_calibration_epoch(passing_events):
    """max scheduled_epoch over PASS/CONDITIONAL events (tie-break created_at ASC).

    The tie-break does not change the value (it's a max of scheduled_epoch), but
    is preserved for parity with suspect window logic. Returns None if empty.
    """
    if not passing_events:
        return None
    return max(e["scheduled_epoch"] for e in passing_events)


# ---------------------------------------------------------------------------
# suspect window — calc suspect_window (PRD §3.5)
# ---------------------------------------------------------------------------
def compute_prior_calibration_epoch(passing_events_before_trigger):
    """max scheduled_epoch among PASS/CONDITIONAL events strictly before trigger."""
    if not passing_events_before_trigger:
        return None
    return max(e["scheduled_epoch"] for e in passing_events_before_trigger)


# ---------------------------------------------------------------------------
# Gage R&R — calc gage_rr_metrics (PRD §3.7)
# ---------------------------------------------------------------------------
def compute_gage_rr(trials, operator_count, part_count, trial_count,
                    process_tolerance):
    """Returns dict with ev, av, grr (6dp), pct_grr (2dp), acceptability.

    Carry full float precision through EV/AV/GRR; round only pct_grr to 2dp.
    ev/av/grr are stored at 6dp round_half_up for display.
    """
    # Build matrix M[o][p] -> list of measured_value
    cells = {}
    for t in trials:
        key = (t["operator_index"], t["part_index"])
        cells.setdefault(key, []).append(t["measured_value"])

    # Step 1: repeatability EV
    ranges = []
    for o in range(1, operator_count + 1):
        for p in range(1, part_count + 1):
            vals = cells.get((o, p), [])
            ranges.append(max(vals) - min(vals))
    rbar = sum(ranges) / len(ranges)
    k1 = K1_BY_TRIAL_COUNT[trial_count]
    ev = rbar * k1

    # Step 2: reproducibility AV
    operator_means = []
    for o in range(1, operator_count + 1):
        ovals = []
        for p in range(1, part_count + 1):
            ovals.extend(cells.get((o, p), []))
        operator_means.append(sum(ovals) / len(ovals))
    xdiff = max(operator_means) - min(operator_means)
    k2 = K2_BY_OPERATOR_COUNT[operator_count]
    inner = (xdiff * k2) ** 2 - (ev ** 2 / (part_count * trial_count))
    av = math.sqrt(max(0.0, inner))

    # Step 3: combined GRR
    grr = math.sqrt(ev ** 2 + av ** 2)

    # Step 4: pct_grr — round ONLY here
    pct_grr = round_half_up(100.0 * (6.0 * grr) / process_tolerance, 2)

    if pct_grr <= 10.00:
        acceptability = "ACCEPTABLE"
    elif pct_grr <= 30.00:
        acceptability = "MARGINAL"
    else:
        acceptability = "UNACCEPTABLE"

    return {
        "ev_repeatability": round_half_up(ev, 6),
        "av_reproducibility": round_half_up(av, 6),
        "grr": round_half_up(grr, 6),
        "pct_grr": pct_grr,
        "acceptability": acceptability,
    }


# ---------------------------------------------------------------------------
# Drift trend — calc drift_trend (PRD §3.8)
# ---------------------------------------------------------------------------
def compute_drift_trend(series, method, tolerance_plus, tolerance_minus):
    """series: list of (x=scheduled_epoch, y=max_abs_deviation), pre-sorted.

    Returns dict { slope, projected_breach_epoch, point_count, method }.
    """
    n = len(series)
    point_count = n
    half_band = max(tolerance_plus, tolerance_minus)

    if n < MIN_POINTS_FOR_LSQ:
        return {
            "slope": None,
            "projected_breach_epoch": None,
            "point_count": point_count,
            "method": method,
        }

    if method == "ENDPOINT":
        x1, y1 = series[0]
        xn, yn = series[-1]
        denom = xn - x1
        if denom == 0:
            slope_raw = None
        else:
            slope_raw = (yn - y1) / denom
    else:  # LSQ
        sx = sum(x for x, _ in series)
        sy = sum(y for _, y in series)
        sxy = sum(x * y for x, y in series)
        sxx = sum(x * x for x, _ in series)
        denom = n * sxx - sx * sx
        if denom == 0:
            slope_raw = None
        else:
            slope_raw = (n * sxy - sx * sy) / denom

    if slope_raw is None:
        slope = None
        projected = None
    else:
        slope = round_half_up(slope_raw, 6)
        projected = _projected_breach_epoch(series[-1], slope, half_band)

    return {
        "slope": slope,
        "projected_breach_epoch": projected,
        "point_count": point_count,
        "method": method,
    }


def _projected_breach_epoch(last_point, slope, half_band):
    """smallest integer e > x_n s.t. y_n + slope*(e - x_n) > half_band.

    Null when slope <= 0.
    """
    if slope is None or slope <= 0:
        return None
    xn, yn = last_point
    # Solve y_n + slope*(e - x_n) > half_band
    # e > x_n + (half_band - y_n)/slope
    threshold = xn + (half_band - yn) / slope
    e = int(math.floor(threshold)) + 1
    if e <= xn:
        e = xn + 1
    # Guard: ensure strict breach (floating safety) — advance until breach holds.
    while not (yn + slope * (e - xn) > half_band):
        e += 1
    return e
