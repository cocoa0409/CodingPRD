"""Decimal discipline (PRD 2.5) and every named calculation of PRD section 3."""

from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP

ZERO = Decimal("0")
D0_2 = Decimal("0.00")
D0_4 = Decimal("0.0000")

# --- plant / melt ------------------------------------------------------------
MELT_YIELD = Decimal("0.92")
DEFAULT_MAX_CULLET_FRACTION = Decimal("0.30")
DEFAULT_CULLET_RESTRICT_FRACTION = Decimal("0.28")
DEFAULT_MAX_WIDTH_CHANGE_IN = Decimal("8.0")
# --- cure --------------------------------------------------------------------
CURE_TEMP_SPAN_F = Decimal("60.0")
DWELL_RATIO_CAP = Decimal("1.25")
MIN_CURE_INDEX = Decimal("100.00")
# --- binder ------------------------------------------------------------------
FORMALDEHYDE_CERT_LIMIT_PPM = Decimal("300")
VOC_CERT_LIMIT_G_PER_KG = Decimal("6.0")
MAX_BINDER_REVISIONS = 2
# --- changeover --------------------------------------------------------------
TRANSITION_BASE_MIN = Decimal("12")
DENSITY_MIN_PER_PCT = Decimal("0.40")
DENSITY_PURGE_CAP_MIN = Decimal("20")
WIDTH_CHANGE_MIN = Decimal("8")
FACING_CHANGE_MIN = Decimal("15")
CHANGEOVER_PURGE_BUFFER_MIN = 30
# --- packaging ---------------------------------------------------------------
RECOVERY_FREE_RATIO = Decimal("4.0")
RECOVERY_LOSS_PCT_PER_RATIO_PT = Decimal("5.0")
FACED_RECOVERY_PENALTY_PCT = Decimal("2.0")
RECOVERY_FLOOR_PCT = Decimal("80.00")
TRUCK_VOLUME_FT3 = Decimal("3800")
TRUCK_PAYLOAD_KG = Decimal("19500")
TRUCK_RATE_USD = Decimal("2450.00")
DECLARED_RECOVERY_MIN_PCT = Decimal("95.0")
RECOVERY_PENALTY_USD_PER_PCT = Decimal("0.0012")
DEFAULT_COMPRESSION_RATIO = Decimal("6.0")
# --- thermal / certification -------------------------------------------------
NONCONFORMANCE_SUSPEND_THRESHOLD = 2
DERATE_STEP = Decimal("0.5")
# --- allocation --------------------------------------------------------------
PEAK_RESERVE_PCT = Decimal("0.15")
OFFPEAK_RESERVE_PCT = Decimal("0.05")
PEAK_MONTHS = (3, 4, 5, 6, 7, 8, 9)
TIER_RANK = {"CONTRACT": 1, "PROGRAM": 2, "SPOT": 3}
# --- scrap -------------------------------------------------------------------
LB_TO_KG = Decimal("0.45359237")
FACING_MASS_FRACTION = Decimal("0.08")
SCRAP_CULLET_RECOVERY = Decimal("0.85")


def q(value, places):
    """Round half up to ``places`` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


def q6(value):
    return q(value, 6)


def trunc(value, places):
    """Truncate toward zero to ``places`` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_DOWN)


def floor_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# PRD 3.3 — packaging economics
# ---------------------------------------------------------------------------

def packaging_economics(compression_ratio, bale_volume_ft3, bale_mass_kg, bag_sqft, facing_type):
    ratio = Decimal(compression_ratio)
    excess = ratio - RECOVERY_FREE_RATIO
    if excess < 0:
        excess = ZERO
    raw = Decimal(100) - q2(excess * RECOVERY_LOSS_PCT_PER_RATIO_PT)
    if facing_type != "UNFACED":
        raw = raw - FACED_RECOVERY_PENALTY_PCT
    recovered = q2(raw)
    if recovered < RECOVERY_FLOOR_PCT:
        recovered = RECOVERY_FLOOR_PCT

    compressed = q3(Decimal(bale_volume_ft3) / ratio)

    by_volume = floor_int(TRUCK_VOLUME_FT3 / compressed) if compressed > 0 else 0
    by_payload = floor_int(TRUCK_PAYLOAD_KG / Decimal(bale_mass_kg)) if Decimal(bale_mass_kg) > 0 else 0
    bales = by_volume if by_volume < by_payload else by_payload

    truck_sqft = Decimal(bales) * Decimal(bag_sqft)
    freight = q6(TRUCK_RATE_USD / truck_sqft) if truck_sqft > 0 else Decimal("0.000000")

    shortfall = DECLARED_RECOVERY_MIN_PCT - recovered
    if shortfall < 0:
        shortfall = ZERO
    penalty = q6(shortfall * RECOVERY_PENALTY_USD_PER_PCT)
    net = q6(freight + penalty)

    return {
        "recovered_thickness_pct": recovered,
        "compressed_bale_volume_ft3": compressed,
        "bales_per_truck": bales,
        "freight_cost_per_sqft": freight,
        "recovery_penalty_per_sqft": penalty,
        "net_landed_cost_per_sqft": net,
    }


# ---------------------------------------------------------------------------
# PRD 3.4 — melt charge, cure index, emissions booking
# ---------------------------------------------------------------------------

def total_charge_kg(target_pull_kg):
    return q2(Decimal(target_pull_kg) / MELT_YIELD)


def allowed_cullet_kg(total_charge, max_cullet_fraction):
    return trunc(Decimal(total_charge) * Decimal(max_cullet_fraction), 2)


def select_cullet(batches, allowed):
    """Whole-batch greedy selection in created_at ascending order."""
    charged = ZERO
    accepted = []
    for batch in batches:
        mass = Decimal(batch["mass_kg"])
        if charged + mass <= allowed:
            charged = charged + mass
            accepted.append(batch)
    return accepted, q2(charged)


def cullet_fraction(charged, total):
    if Decimal(total) == 0:
        return D0_4
    return q4(Decimal(charged) / Decimal(total))


def dwell_seconds(oven_length_ft, line_speed_fpm):
    return q2(Decimal(oven_length_ft) / Decimal(line_speed_fpm) * Decimal(60))


def cure_index(dwell_s, min_dwell_s, avg_zone_temp_f, min_cure_temp_f):
    margin = (Decimal(avg_zone_temp_f) - Decimal(min_cure_temp_f)) / CURE_TEMP_SPAN_F
    if margin < 0:
        margin = ZERO
    if margin > 1:
        margin = Decimal(1)
    ratio = Decimal(dwell_s) / Decimal(min_dwell_s)
    if ratio > DWELL_RATIO_CAP:
        ratio = DWELL_RATIO_CAP
    return q2(ratio * (Decimal(1) + margin) / Decimal(2) * Decimal(100))


def formaldehyde_kg(binder_applied_kg, formaldehyde_ppm):
    return q4(Decimal(binder_applied_kg) * Decimal(formaldehyde_ppm) / Decimal(1000000))


def voc_kg(binder_applied_kg, voc_g_per_kg):
    return q4(Decimal(binder_applied_kg) * Decimal(voc_g_per_kg) / Decimal(1000))


# ---------------------------------------------------------------------------
# PRD 3.5 — changeover purge scrap
# ---------------------------------------------------------------------------

def density_delta(from_density, to_density):
    """Returns (stored_4dp, estimate_2dp)."""
    raw = abs(Decimal(to_density) - Decimal(from_density)) / Decimal(from_density) * Decimal(100)
    return q4(raw), q2(raw)


def purge_minutes(delta_pct_2dp, width_changed, facing_changed):
    density_term = q2(Decimal(delta_pct_2dp) * DENSITY_MIN_PER_PCT)
    if density_term > DENSITY_PURGE_CAP_MIN:
        density_term = DENSITY_PURGE_CAP_MIN
    total = TRANSITION_BASE_MIN + density_term
    if width_changed:
        total = total + WIDTH_CHANGE_MIN
    if facing_changed:
        total = total + FACING_CHANGE_MIN
    return q2(total)


def provisional_scrap_kg(purge_min, mass_rate_kg_per_min):
    return q2(Decimal(purge_min) * Decimal(mass_rate_kg_per_min))


# ---------------------------------------------------------------------------
# PRD 3.6 — thermal verdict and derate grid
# ---------------------------------------------------------------------------

def conformance_floor(declared_r_value_at_test, r_value_tolerance):
    return q2(Decimal(declared_r_value_at_test) - Decimal(r_value_tolerance))


def specimen_stats(values):
    total = ZERO
    for value in values:
        total = total + Decimal(value)
    count = len(values)
    mean = q2(total / Decimal(count))
    smallest = min(Decimal(v) for v in values)
    return count, mean, q2(smallest)


def derated_value(basis_value):
    steps = floor_int(Decimal(basis_value) / DERATE_STEP)
    return q2(Decimal(steps) * DERATE_STEP)


# ---------------------------------------------------------------------------
# PRD 3.7 — quarantine scrap recovery
# ---------------------------------------------------------------------------

def scrap_cullet_mass(weighed_scrap_lb, bags, bale_mass_kg, facing_type):
    if weighed_scrap_lb is not None:
        gross = q2(Decimal(weighed_scrap_lb) * LB_TO_KG)
    else:
        gross = q2(Decimal(bags) * Decimal(bale_mass_kg))
    glass = gross if facing_type == "UNFACED" else q2(gross * (Decimal(1) - FACING_MASS_FRACTION))
    return q2(glass * SCRAP_CULLET_RECOVERY)


# ---------------------------------------------------------------------------
# PRD 3.8 — seasonal reserve and shortage ratio
# ---------------------------------------------------------------------------

def is_peak_season(period_start_dt):
    return period_start_dt.month in PEAK_MONTHS


def seasonal_reserve(total_available, peak):
    pct = PEAK_RESERVE_PCT if peak else OFFPEAK_RESERVE_PCT
    return q2(Decimal(total_available) * pct)


def shortage_ratio(allocatable, total_requested):
    if Decimal(total_requested) == 0:
        return Decimal("1.0000")
    ratio = q4(Decimal(allocatable) / Decimal(total_requested))
    return ratio if ratio < Decimal("1.0000") else Decimal("1.0000")


def whole_bag_grant(amount, bag_sqft):
    bags = floor_int(Decimal(amount) / Decimal(bag_sqft))
    return bags, q2(Decimal(bags) * Decimal(bag_sqft))


def exact_bag_multiple(amount, bag_sqft):
    """Returns the whole bag count when ``amount`` is an exact positive multiple
    of ``bag_sqft``, otherwise None."""
    value = Decimal(amount)
    bag = Decimal(bag_sqft)
    if value <= 0 or bag <= 0:
        return None
    quotient = value / bag
    if quotient != quotient.to_integral_value():
        return None
    return int(quotient)
