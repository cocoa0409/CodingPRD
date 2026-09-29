"""Every calculation from PRD section 3 / scaffold section 1.4."""

from datetime import timedelta
from decimal import Decimal

from util import D, q2, q3, q4, ZERO

# ---------------------------------------------------------------- registers

PRODUCT_LINES = ("HIGHWAY_DEICING", "WATER_CONDITIONING", "FOOD_GRADE",
                 "CHEMICAL_FEEDSTOCK")

SCREEN_SPECS = ("COARSE", "MEDIUM", "FINE")

STORAGE_KINDS = ("COVERED", "OPEN_PAD")

PRODUCT_SPECS = {
    "HIGHWAY_DEICING": {
        "min_purity": D("92.0"),
        "screens": ("COARSE", "MEDIUM"),
        "anticaking": (D("0"), D("60")),
        "inhibitor": (D("0.0"), D("1.5")),
        "moisture_sensitive": False,
    },
    "WATER_CONDITIONING": {
        "min_purity": D("99.5"),
        "screens": ("COARSE",),
        "anticaking": (D("0"), D("0")),
        "inhibitor": (D("0.0"), D("0.0")),
        "moisture_sensitive": True,
    },
    "FOOD_GRADE": {
        "min_purity": D("99.6"),
        "screens": ("FINE",),
        "anticaking": (D("4"), D("12")),
        "inhibitor": (D("0.0"), D("0.0")),
        "moisture_sensitive": True,
    },
    "CHEMICAL_FEEDSTOCK": {
        "min_purity": D("96.0"),
        "screens": ("MEDIUM", "FINE"),
        "anticaking": (D("0"), D("25")),
        "inhibitor": (D("0.0"), D("0.0")),
        "moisture_sensitive": True,
    },
}

SCREEN_YIELD = {"COARSE": D("0.94"), "MEDIUM": D("0.90"), "FINE": D("0.82")}
SCREEN_UPGRADE = {"COARSE": D("0.5"), "MEDIUM": D("1.2"), "FINE": D("2.5")}

HOIST_FACTOR = {
    "HOIST_AVAILABLE": D("1.00"),
    "HOIST_DERATED": D("0.55"),
    "HOIST_DOWN": D("0.00"),
}

COMPLIANCE_FACTOR = {
    "COMPLIANT": D("1.00"),
    "CITED": D("0.80"),
    "WITHDRAWAL_ORDER": D("0.00"),
}

MODE_BUFFER_MINUTES = {"RAIL": 45, "BARGE": 20, "TRUCK": 0}

AUTO_SURGE_THRESHOLD_PCT = D("90")


# ---------------------------------------------------- panel recoverable tons

def panel_recoverable_tons(panel, mine):
    gross = D(panel["gross_tons_in_place"])
    ratio = D(panel["extraction_ratio_pct"])
    grade = D(panel["grade_pct_nacl"])
    insolubles = D(panel["insolubles_pct"])

    base = gross * (ratio / D(100))

    if grade >= D("95.0"):
        grade_factor = D("1.00")
    elif grade >= D("90.0"):
        grade_factor = D("0.96")
    else:
        grade_factor = D("0.88")

    excess = insolubles - D("3.0")
    if excess < ZERO:
        excess = ZERO
    insolubles_penalty = excess * D("0.012")
    if insolubles_penalty > D("0.20"):
        insolubles_penalty = D("0.20")

    pillar_bonus = ZERO
    if panel.get("pillar_recovery_allowed") and mine["compliance_state"] == "COMPLIANT":
        pillar_bonus = D("0.08") * (gross - base)

    uncapped = base * grade_factor * (D(1) - insolubles_penalty) + pillar_bonus
    hard_cap = gross * D("0.72")
    return q2(min(uncapped, hard_cap))


# ------------------------------------------------------------ mine capacity

def mine_factors(mine):
    return (HOIST_FACTOR[mine["hoist_state"]],
            COMPLIANCE_FACTOR[mine["compliance_state"]])


def mine_effective_hoist(mine):
    hoist_factor, compliance_factor = mine_factors(mine)
    return q2(D(mine["rated_hoist_tons_per_day"]) * hoist_factor * compliance_factor)


def mine_hourly_capacity(mine):
    """effective / 24, deliberately unrounded."""
    return D(mine["effective_hoist_tons_per_day"]) / D(24)


# ------------------------------------------------------- hoist window sweep

def window_hours(start, end):
    seconds = D(str((end - start).total_seconds()))
    return seconds / D(3600)


def planned_rate(planned_tons, start, end):
    return q4(D(planned_tons) / window_hours(start, end))


def _segments(intervals):
    """intervals: list of (start, end, rate). Yields (a, b, rate_sum)."""
    times = sorted({t for iv in intervals for t in (iv[0], iv[1])})
    out = []
    for i in range(len(times) - 1):
        a, b = times[i], times[i + 1]
        total = ZERO
        for (s, e, r) in intervals:
            if s <= a and e >= b:
                total += D(r)
        out.append((a, b, total))
    return out


def peak_rate_in_window(cand_start, cand_end, cand_rate, peers):
    """Peak aggregate concurrent rate at instants inside the candidate window.

    Windows are half-open [start, end): a run that ends exactly when another
    begins never overlaps it.
    """
    intervals = [(cand_start, cand_end, D(cand_rate))]
    for peer in peers:
        intervals.append((peer["hoist_window_start"], peer["hoist_window_end"],
                          D(peer["planned_tons_per_hour"])))
    peak = ZERO
    for (a, b, total) in _segments(intervals):
        if b <= cand_start or a >= cand_end:
            continue
        if total > peak:
            peak = total
    return peak


def over_capacity_segments(runs, capacity):
    intervals = [(r["hoist_window_start"], r["hoist_window_end"],
                  D(r["planned_tons_per_hour"])) for r in runs]
    if not intervals:
        return []
    return [(a, b) for (a, b, total) in _segments(intervals) if total > capacity]


def run_overlaps(run, a, b):
    return run["hoist_window_start"] < b and run["hoist_window_end"] > a


# ------------------------------------------------------- loadout bay geometry

def buffer_minutes(mode):
    return MODE_BUFFER_MINUTES[mode]


def bay_conflict(new_mode, new_start, new_end, peers):
    """Closed, buffered, pairwise-exclusive. Returns the first colliding peer."""
    new_buffer = buffer_minutes(new_mode)
    for peer in peers:
        gap = max(new_buffer, buffer_minutes(peer["mode"]))
        delta = timedelta(minutes=gap)
        blocked_from = peer["load_window_start"] - delta
        blocked_to = peer["load_window_end"] + delta
        if new_start <= blocked_to and new_end >= blocked_from:
            return peer
    return None


# ------------------------------------------------------ treatment & purity

def treatment_yield_tons(input_tons, screen_spec, moisture_pct, rework_count):
    screen = SCREEN_YIELD[screen_spec]
    moisture_factor = D(1) - (D(moisture_pct) / D(100))
    rework_loss = D("0.97") ** int(rework_count)
    return q2(D(input_tons) * screen * moisture_factor * rework_loss)


def treatment_purity(grade_pct_nacl, screen_spec):
    upgraded = D(grade_pct_nacl) + SCREEN_UPGRADE[screen_spec]
    return q3(min(D("99.9"), upgraded))


# --------------------------------------------------------- season forecast

def forecast_targets(forecast):
    normal = D(forecast["normal_season_tons"])
    severity = D(forecast["severity_index"])

    w_severe = severity / D(100)
    w_mild = ((D(100) - severity) / D(100)) * D("0.40")
    w_normal = D(1) - w_severe - w_mild
    severity_weighted = q2(
        (normal * D("0.75") * w_mild
         + normal * D("1.00") * w_normal
         + normal * D("1.40") * w_severe) * D("1.05"))

    p1 = D(forecast["prior_season_1_actual_tons"])
    p2 = D(forecast["prior_season_2_actual_tons"])
    p3 = D(forecast["prior_season_3_actual_tons"])
    weighted_trailing = (p1 * D(3) + p2 * D(2) + p3 * D(1)) / D(6)
    if severity <= D(40):
        uplift = D("1.00")
    elif severity <= D(70):
        uplift = D("1.10")
    else:
        uplift = D("1.25")
    trailing_baseline = q2(weighted_trailing * uplift * D("1.05"))

    return severity_weighted, trailing_baseline


# ------------------------------------------------------------- penalties

def order_shortfall_penalty(order, contract, allocated_tons=None):
    if allocated_tons is None:
        allocated_tons = order.get("allocated_tons") or 0
    shorted = D(order["requested_tons"]) - D(allocated_tons)
    if shorted < ZERO:
        shorted = ZERO
    multiplier = D("2.00") if order["storm_priority"] == "STORM_EMERGENCY" else D("1.00")
    raw = shorted * D(contract["failure_to_supply_penalty_per_ton"]) * multiplier
    order_value = q2(D(order["requested_tons"]) * D(contract["guaranteed_price_per_ton"]))
    ceiling = order_value * D("0.15")
    return q2(min(raw, ceiling))


def season_penalty(contract, fulfilled_tons):
    committed = D(contract["committed_tons"])
    season_shorted = committed - D(fulfilled_tons)
    if season_shorted < ZERO:
        season_shorted = ZERO
    tolerance = committed * (D(100) - D(contract["min_take_pct"])) / D(100)
    billable = season_shorted - tolerance
    if billable < ZERO:
        billable = ZERO
    return q2(billable * D(contract["failure_to_supply_penalty_per_ton"]))
