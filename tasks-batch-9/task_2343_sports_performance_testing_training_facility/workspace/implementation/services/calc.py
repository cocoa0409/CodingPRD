"""Pure calculation rules (PRD 2.7 and 3.x).

Every arithmetic step uses decimal.Decimal with ROUND_HALF_UP - PRD 2.7 pins
all rounding in this domain as round-half-up (a midpoint rounds away from
zero).  Python's built-in round() is never used.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# ------------------------------------------------------------- constants ----
MOVEMENT_SCREEN_METRICS = (
    "OH_SQUAT",
    "HURDLE_STEP",
    "INLINE_LUNGE",
    "SL_HOP_L",
    "SL_HOP_R",
)
SCREEN_ITEM_MAX = 3
SCREEN_RAW_MAX = 15
SCREEN_ASYMMETRY_WEIGHT = Decimal("2.0")
RISK_SCORE_CAP = Decimal("30.00")
RESTRICTED_RISK_THRESHOLD = Decimal("12.00")
REASSESSMENT_MULTIPLIER_CAP = Decimal("1.45")
REASSESSMENT_MULTIPLIER_STEP = Decimal("0.15")

PERFORMANCE_METRICS = ("CMJ_CM", "SPRINT_10M_S", "IMTP_N")
METRIC_WEIGHTS = {
    "CMJ_CM": Decimal("0.40"),
    "SPRINT_10M_S": Decimal("0.35"),
    "IMTP_N": Decimal("0.25"),
}
P50_ANCHOR = Decimal("50")
P90_SPAN = Decimal("40")
PERCENTILE_FLOOR = Decimal("1.0")
PERCENTILE_CEILING = Decimal("99.0")
MATURITY_OFFSET_TRIGGER_MONTHS = 12
TEST_CADENCE_DAYS = 56

READINESS_DEFAULT_BASE = Decimal("50.0")
READINESS_DECAY_GRACE_DAYS = 30
READINESS_DECAY_PER_DAY = Decimal("0.5")
READINESS_DECAY_CAP = Decimal("20.0")
ATTENDANCE_TARGET = Decimal("0.80")
ATTENDANCE_SPAN = Decimal("10")
RTS_READINESS_PENALTY = Decimal("15.0")
COMPETITION_READINESS_MIN = Decimal("60.00")

UNIT_RTS = Decimal("2.5")
UNIT_YOUTH = Decimal("1.5")
UNIT_STANDARD = Decimal("1.0")
YOUTH_AGE_MAX = 12
BASE_RATIO_ONSITE = Decimal("8")
BASE_RATIO_OFFSITE = Decimal("4")
STATIONS_PER_COACH = Decimal("3")

DROP_IN_RATE_CENTS = 4500
OFFSITE_SURCHARGE_CENTS = 1500
NO_SHOW_FEE_PCT = Decimal("0.275")
NO_SHOW_MULTIPLIERS = {1: Decimal("1.0"), 2: Decimal("1.0"), 3: Decimal("1.5")}
NO_SHOW_MULTIPLIER_HIGH = Decimal("2.0")
NO_SHOW_SUSPENSION_THRESHOLD = 3

TIER_MULTIPLIERS = {
    "TIER_1": Decimal("1.00"),
    "TIER_2": Decimal("0.92"),
    "TIER_3": Decimal("0.85"),
}
TIER_2_MIN_DELIVERED = 2
TIER_3_MIN_DELIVERED = 5
OFFSITE_RATE_MULTIPLIER = Decimal("1.20")

LATE_CANCEL_WINDOW_HOURS = 24
TRAVEL_BUFFER_MINUTES = 30
FACILITY_MAX_CONCURRENT_ONSITE = 3
RTS_MAX_STAGE_ATTEMPTS = 2

# sport | position | age band | metric | p50 | p90 | direction
NORM_TABLE = [
    ("BASKETBALL", "GUARD", 13, 14, "CMJ_CM", Decimal("34.0"), Decimal("42.0"), "HIGHER_BETTER"),
    ("BASKETBALL", "GUARD", 13, 14, "SPRINT_10M_S", Decimal("1.85"), Decimal("1.69"), "LOWER_BETTER"),
    ("BASKETBALL", "GUARD", 13, 14, "IMTP_N", Decimal("1400"), Decimal("1900"), "HIGHER_BETTER"),
    ("BASKETBALL", "GUARD", 15, 16, "CMJ_CM", Decimal("40.0"), Decimal("50.0"), "HIGHER_BETTER"),
    ("BASKETBALL", "GUARD", 15, 16, "SPRINT_10M_S", Decimal("1.78"), Decimal("1.62"), "LOWER_BETTER"),
    ("BASKETBALL", "GUARD", 15, 16, "IMTP_N", Decimal("1700"), Decimal("2300"), "HIGHER_BETTER"),
    ("BASKETBALL", "GUARD", 17, 18, "CMJ_CM", Decimal("45.0"), Decimal("56.0"), "HIGHER_BETTER"),
    ("BASKETBALL", "GUARD", 17, 18, "SPRINT_10M_S", Decimal("1.72"), Decimal("1.56"), "LOWER_BETTER"),
    ("BASKETBALL", "GUARD", 17, 18, "IMTP_N", Decimal("2000"), Decimal("2650"), "HIGHER_BETTER"),
    ("SOCCER", "MIDFIELDER", 15, 16, "CMJ_CM", Decimal("36.0"), Decimal("45.0"), "HIGHER_BETTER"),
    ("SOCCER", "MIDFIELDER", 15, 16, "SPRINT_10M_S", Decimal("1.80"), Decimal("1.64"), "LOWER_BETTER"),
    ("SOCCER", "MIDFIELDER", 15, 16, "IMTP_N", Decimal("1600"), Decimal("2150"), "HIGHER_BETTER"),
]


# ------------------------------------------------------------- primitives ----
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    return int((D(numerator) / D(denominator)).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def as_float(value):
    if value is None:
        return None
    return float(value)


def clamp(value, low, high):
    value = D(value)
    if value < D(low):
        return D(low)
    if value > D(high):
        return D(high)
    return value


# ------------------------------------------------------- age computation ----
def age_years_from(dob, reference_date):
    days = (reference_date - dob).days
    return floor_int(D(days) / D("365.25"))


# --------------------------------------------- movement screen risk score ----
def movement_screen_risk(values, screen_count, active_rehab_count):
    """values: {metric_code: int}.  Returns (risk_score, asymmetry_points,
    variant_applied, history_multiplier)."""
    raw_total = sum(D(values[code]) for code in MOVEMENT_SCREEN_METRICS)
    asymmetry = abs(D(values["SL_HOP_L"]) - D(values["SL_HOP_R"]))
    deficit = D(SCREEN_RAW_MAX) - raw_total + SCREEN_ASYMMETRY_WEIGHT * asymmetry
    if screen_count == 0:
        variant = "INTAKE_SCREEN"
        multiplier = Decimal("1.00")
    else:
        variant = "REASSESSMENT_SCREEN"
        multiplier = REASSESSMENT_MULTIPLIER_STEP * D(active_rehab_count) + Decimal("1")
        if multiplier > REASSESSMENT_MULTIPLIER_CAP:
            multiplier = REASSESSMENT_MULTIPLIER_CAP
    scaled = deficit * multiplier
    if scaled < 0:
        scaled = Decimal("0")
    if scaled > RISK_SCORE_CAP:
        scaled = RISK_SCORE_CAP
    return rhu(scaled, 2), int(asymmetry), variant, multiplier


# ------------------------------------------- normative percentile scoring ----
def maturity_lookup_age(age_years_at_test, maturity_offset_months):
    """Returns (lookup_age, variant_applied)."""
    if abs(int(maturity_offset_months)) >= MATURITY_OFFSET_TRIGGER_MONTHS:
        shift = int(rhu(D(maturity_offset_months) / D(12), 0))
        return age_years_at_test + shift, "MATURITY_ADJUSTED"
    return age_years_at_test, "RAW_NORM"


def find_norm_row(sport, position, lookup_age, metric_code):
    for row in NORM_TABLE:
        if row[0] != sport or row[1] != position:
            continue
        if not (row[2] <= lookup_age <= row[3]):
            continue
        if row[4] != metric_code:
            continue
        return row
    return None


def find_norm_band(sport, position, lookup_age):
    for row in NORM_TABLE:
        if row[0] == sport and row[1] == position and row[2] <= lookup_age <= row[3]:
            return (row[2], row[3])
    return None


def band_label(sport, position, band):
    return "%s/%s/%d-%d" % (sport, position, band[0], band[1])


def metric_percentile(value, row):
    p50 = row[5]
    p90 = row[6]
    direction = row[7]
    value = D(value)
    if direction == "HIGHER_BETTER":
        raw = P50_ANCHOR + P90_SPAN * (value - p50) / (p90 - p50)
    else:
        raw = P50_ANCHOR + P90_SPAN * (p50 - value) / (p50 - p90)
    return rhu(clamp(raw, PERCENTILE_FLOOR, PERCENTILE_CEILING), 1)


def composite_percentile(scored):
    """scored: list of (metric_code, percentile Decimal).  Weights of matched
    metrics are renormalised; the composite is rounded once, to 1 decimal."""
    if not scored:
        return None
    weight_total = Decimal("0")
    weighted = Decimal("0")
    for metric_code, percentile in scored:
        weight = METRIC_WEIGHTS[metric_code]
        weight_total += weight
        weighted += percentile * weight
    if weight_total == 0:
        return None
    return rhu(weighted / weight_total, 1)


# ------------------------------------------------------- readiness index ----
def readiness_index(base_percentile, days_since_test, attended_count, no_show_count, rts_open):
    base = D(base_percentile) if base_percentile is not None else READINESS_DEFAULT_BASE
    overdue = days_since_test - READINESS_DECAY_GRACE_DAYS
    if overdue < 0:
        overdue = 0
    decay = READINESS_DECAY_PER_DAY * D(overdue)
    if decay > READINESS_DECAY_CAP:
        decay = READINESS_DECAY_CAP
    total = attended_count + no_show_count
    if total == 0:
        attendance_adjust = Decimal("0.0")
    else:
        rate = D(attended_count) / D(total)
        attendance_adjust = rhu(ATTENDANCE_SPAN * (rate - ATTENDANCE_TARGET), 1)
    penalty = RTS_READINESS_PENALTY if rts_open else Decimal("0")
    raw = base - decay + attendance_adjust - penalty
    return rhu(clamp(raw, 0, 100), 2)


# ------------------------------------------------ coach ratio requirement ----
def athlete_unit(age_years, rts_open):
    if rts_open:
        return UNIT_RTS
    if age_years <= YOUTH_AGE_MAX:
        return UNIT_YOUTH
    return UNIT_STANDARD


def required_coach_count(athlete_units, site_code, station_count):
    base_ratio = BASE_RATIO_OFFSITE if site_code == "OFFSITE" else BASE_RATIO_ONSITE
    ratio_requirement = ceil_div(athlete_units, base_ratio)
    station_requirement = ceil_div(station_count, STATIONS_PER_COACH)
    return max(1, ratio_requirement, station_requirement)


# ----------------------------------------------------------------- money ----
def drop_in_charge_cents(site_code):
    charge = DROP_IN_RATE_CENTS
    if site_code == "OFFSITE":
        charge += OFFSITE_SURCHARGE_CENTS
    return charge


def no_show_fee_cents(strike_index):
    multiplier = NO_SHOW_MULTIPLIERS.get(strike_index, NO_SHOW_MULTIPLIER_HIGH)
    return int(rhu(D(DROP_IN_RATE_CENTS) * NO_SHOW_FEE_PCT * multiplier, 0))


def rate_tier_for(sessions_delivered):
    if sessions_delivered < TIER_2_MIN_DELIVERED:
        return "TIER_1"
    if sessions_delivered < TIER_3_MIN_DELIVERED:
        return "TIER_2"
    return "TIER_3"


def billed_rate_cents(base_rate_cents, tier, site_code):
    multiplier = TIER_MULTIPLIERS[tier]
    site_multiplier = OFFSITE_RATE_MULTIPLIER if site_code == "OFFSITE" else Decimal("1")
    return int(rhu(D(base_rate_cents) * multiplier * site_multiplier, 0))


# ---------------------------------------------------- program planned load ----
def block_load(weekly_volume_units, start_week, end_week, target_intensity_pct):
    weeks = D(end_week) - D(start_week) + Decimal("1")
    return rhu(D(weekly_volume_units) * weeks * (D(target_intensity_pct) / D(100)), 2)


def program_planned_load(blocks):
    """blocks already ordered by sequence_index ASC."""
    total = Decimal("0")
    for block in blocks:
        total += block_load(
            block["weekly_volume_units"],
            block["start_week"],
            block["end_week"],
            block["target_intensity_pct"],
        )
    return total


def program_total_weeks(blocks):
    if not blocks:
        return 0
    return max(b["end_week"] for b in blocks) - min(b["start_week"] for b in blocks) + 1


# ------------------------------------------------------------- reporting ----
def attendance_rate_pct(attended_count, no_show_count):
    total = attended_count + no_show_count
    if total == 0:
        return None
    return rhu(D(100) * D(attended_count) / D(total), 1)
