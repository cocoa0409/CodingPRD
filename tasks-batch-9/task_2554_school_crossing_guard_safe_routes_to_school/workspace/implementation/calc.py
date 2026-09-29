"""Every calculation in the specification.  All arithmetic is exact decimal;
every rounding operation is round half up (PRD 2.8)."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 40

Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
Q0 = Decimal("1")

D0 = Decimal("0")
D100 = Decimal("100")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return D0
    return Decimal(str(value))


def r2(value):
    return dec(value).quantize(Q2, rounding=ROUND_HALF_UP)


def r4(value):
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def rcent(value):
    """Round half up to a whole cent."""
    return int(dec(value).quantize(Q0, rounding=ROUND_HALF_UP))


def f2(value):
    return float(r2(value))


def f4(value):
    return float(r4(value))


# ---------------------------------------------------------------------------
# Warrant score (PRD 3.3)
# ---------------------------------------------------------------------------
SPEED_MULT_HIGH = Decimal("1.30")
SPEED_MULT_MID = Decimal("1.15")
SPEED_MULT_BASE = Decimal("1.00")

CRASH_POINTS_PEDESTRIAN = Decimal("5.0")
CRASH_POINTS_SEVERE_EXTRA = Decimal("10.0")
CRASH_TERM_CAP = Decimal("25.0")
SCORE_CAP = Decimal("100.0")

GAP_WEIGHT_UNCONTROLLED = Decimal("45.0")
GAP_WEIGHT_CONTROLLED = Decimal("20.0")
GAP_CAP_CONTROLLED = Decimal("20.0")
EXPOSURE_DIVISOR_UNCONTROLLED = Decimal("10000.0")
EXPOSURE_DIVISOR_CONTROLLED = Decimal("8000.0")
EXPOSURE_CAP_UNCONTROLLED = Decimal("40.0")
EXPOSURE_CAP_CONTROLLED = Decimal("55.0")

CRASH_LOOKBACK_DAYS = 1095


def speed_multiplier(speed_limit_mph):
    speed = int(speed_limit_mph)
    if speed >= 35:
        return SPEED_MULT_HIGH
    if speed >= 30:
        return SPEED_MULT_MID
    return SPEED_MULT_BASE


def gap_deficit_ratio(adequate_gaps, child_count):
    denominator = Decimal(max(1, int(child_count)))
    raw = Decimal(1) - (Decimal(int(adequate_gaps)) / denominator)
    if raw < 0:
        raw = D0
    return r4(raw)


def crash_term(pedestrian_crashes, severe_crashes):
    term = (CRASH_POINTS_PEDESTRIAN * Decimal(int(pedestrian_crashes))
            + CRASH_POINTS_SEVERE_EXTRA * Decimal(int(severe_crashes)))
    return min(CRASH_TERM_CAP, term)


def warrant_score(variant, speed_limit_mph, child_count, vehicle_count,
                  adequate_gaps, pedestrian_crashes, severe_crashes):
    mult = speed_multiplier(speed_limit_mph)
    ratio = gap_deficit_ratio(adequate_gaps, child_count)
    crash = crash_term(pedestrian_crashes, severe_crashes)
    product = Decimal(int(child_count)) * Decimal(int(vehicle_count))
    if variant == "GAP_ADEQUACY":
        exposure = min(EXPOSURE_CAP_UNCONTROLLED,
                       product / EXPOSURE_DIVISOR_UNCONTROLLED)
        gap_term = GAP_WEIGHT_UNCONTROLLED * ratio
    else:
        exposure = min(EXPOSURE_CAP_CONTROLLED,
                       product / EXPOSURE_DIVISOR_CONTROLLED)
        gap_term = min(GAP_CAP_CONTROLLED, GAP_WEIGHT_CONTROLLED * ratio)
    raw = (gap_term + exposure + crash) * mult
    return r2(min(SCORE_CAP, raw))


WARRANT_THRESHOLD = Decimal("60.00")
CONDITIONAL_THRESHOLD = Decimal("40.00")


def warrant_determination(score, pedestrian_crash_count_3yr):
    score = dec(score)
    if score >= WARRANT_THRESHOLD:
        return "WARRANTED"
    if score >= CONDITIONAL_THRESHOLD and int(pedestrian_crash_count_3yr) >= 1:
        return "CONDITIONAL"
    return "NOT_WARRANTED"


# ---------------------------------------------------------------------------
# Crash severity weighting (PRD 3.2 / 3.8)
# ---------------------------------------------------------------------------
SEVERITY_POINTS = {
    "PROPERTY_DAMAGE_ONLY": 3,
    "INJURY": 8,
    "SEVERE_INJURY": 15,
    "FATAL": 25,
}
SEVERE_SEVERITIES = ("SEVERE_INJURY", "FATAL")


def severity_points(entries):
    return sum(SEVERITY_POINTS.get(e.get("severity"), 0) for e in entries)


# ---------------------------------------------------------------------------
# Guard reliability (PRD 3.4)
# ---------------------------------------------------------------------------
TRAINING_BONUS_CAP = Decimal("10.0")
ROLLING_ABSENCE_PENALTY = Decimal("4.0")
ROLLING_UNEXCUSED_PENALTY = Decimal("6.0")
SEASON_ABSENCE_PENALTY = Decimal("2.5")
SEASON_UNEXCUSED_PENALTY = Decimal("7.5")
RELIABILITY_FLOOR = Decimal("75.00")
ROLLING_WINDOW_DAYS = 90


def training_bonus(training_hours_completed):
    blocks = int(dec(training_hours_completed) // Decimal(4))
    if blocks < 0:
        blocks = 0
    return min(TRAINING_BONUS_CAP, Decimal(blocks))


def reliability_score(training_hours_completed, absence_count, unexcused_count,
                      variant):
    if variant == "ROLLING_90D":
        penalty = (ROLLING_ABSENCE_PENALTY * Decimal(absence_count)
                   + ROLLING_UNEXCUSED_PENALTY * Decimal(unexcused_count))
    else:
        penalty = (SEASON_ABSENCE_PENALTY * Decimal(absence_count)
                   + SEASON_UNEXCUSED_PENALTY * Decimal(unexcused_count))
    raw = Decimal("100.0") - penalty + training_bonus(training_hours_completed)
    raw = min(Decimal("100.0"), raw)
    raw = max(D0, raw)
    return r2(raw)


# ---------------------------------------------------------------------------
# Walking route hazard score (PRD 3.7)
# ---------------------------------------------------------------------------
HAZARD_WEIGHTS = {
    "NO_SIDEWALK": Decimal("1.25"),
    "UNCONTROLLED_CROSSING": Decimal("3.50"),
    "HIGH_SPEED_ARTERIAL": Decimal("2.75"),
    "RAIL_CROSSING": Decimal("4.00"),
    "DRIVEWAY_CONFLICT": Decimal("0.85"),
    "POOR_LIGHTING": Decimal("0.60"),
}
HAZARD_TYPES = tuple(HAZARD_WEIGHTS.keys())
HAZARD_SCORE_CEILING = Decimal("25.00")


def route_hazard_score(segments):
    """Per-segment round first, then sum, then round the sum (normative)."""
    total = D0
    for seg in sorted(segments, key=lambda s: s["segment_order"]):
        if seg.get("mitigated"):
            seg_score = Decimal("0.00")
        else:
            weight = HAZARD_WEIGHTS[seg["hazard_type"]]
            seg_score = r2(weight * Decimal(int(seg["length_ft"])) / Decimal("100.0"))
        total = total + seg_score
    return r2(total)


# ---------------------------------------------------------------------------
# Substitute cost (PRD 3.6)
# ---------------------------------------------------------------------------
GUARD_HOURLY_RATE_CENTS = Decimal("1850")
SHIFT_HOURS_SINGLE = Decimal("1.50")
SHIFT_HOURS_BOTH = Decimal("3.00")
SURGE_PCT = {
    "SAME_DAY": Decimal("0.35"),
    "SHORT": Decimal("0.15"),
    "STANDARD": Decimal("0.00"),
}
FEE_TIER_THRESHOLD_CENTS = 4000
ADMIN_FEE_PCT_HIGH = Decimal("0.08")
ADMIN_FEE_PCT_LOW = Decimal("0.05")
ATTEMPT_PENALTY_CENTS = 250
OFFER_TTL_MINUTES = 45

SAME_DAY_HOURS = Decimal("12")
SHORT_HOURS = Decimal("48")


def urgency_tier(notice_hours):
    hours = dec(notice_hours)
    if hours < SAME_DAY_HOURS:
        return "SAME_DAY"
    if hours < SHORT_HOURS:
        return "SHORT"
    return "STANDARD"


def substitute_cost_cents(shift, tier, dispatch_attempt_count):
    shift_hours = SHIFT_HOURS_BOTH if shift == "BOTH" else SHIFT_HOURS_SINGLE
    base_cents = rcent(GUARD_HOURLY_RATE_CENTS * shift_hours)
    surge_cents = rcent(Decimal(base_cents) * SURGE_PCT[tier])
    subtotal_cents = base_cents + surge_cents
    fee_pct = (ADMIN_FEE_PCT_HIGH if subtotal_cents >= FEE_TIER_THRESHOLD_CENTS
               else ADMIN_FEE_PCT_LOW)
    admin_fee_cents = rcent(Decimal(subtotal_cents) * fee_pct)
    attempts = int(dispatch_attempt_count)
    penalty = ATTEMPT_PENALTY_CENTS * max(0, attempts - 1)
    return subtotal_cents + admin_fee_cents + penalty


# ---------------------------------------------------------------------------
# School coverage posture (PRD 2.7)
# ---------------------------------------------------------------------------
SUSPEND_THRESHOLD_PCT = Decimal("50.00")


def coverage_rate_pct(covered_post_count, active_post_count):
    if int(active_post_count) == 0:
        return Decimal("100.00")
    return r2(D100 * Decimal(int(covered_post_count)) / Decimal(int(active_post_count)))


def coverage_posture(uncovered_post_count, rate_pct):
    if int(uncovered_post_count) == 0:
        return "OPEN"
    if dec(rate_pct) < SUSPEND_THRESHOLD_PCT:
        return "SUSPENDED"
    return "RESTRICTED"


# ---------------------------------------------------------------------------
# Project benefit-cost score (PRD 3.8)
# ---------------------------------------------------------------------------
WEIGHT_WARRANT = Decimal("0.40")
WEIGHT_CRASH = Decimal("0.25")
WEIGHT_STUDENTS = Decimal("0.20")
WEIGHT_COMPLAINTS = Decimal("0.15")
CAP_CRASH_POINTS = Decimal("60.0")
CAP_STUDENT_POINTS = Decimal("50.0")
CAP_COMPLAINT_POINTS = Decimal("30.0")
COMPLAINT_POINTS_EACH = Decimal("5.0")
STUDENTS_PER_POINT = Decimal("10.0")
COST_FACTOR_DIVISOR_CENTS = Decimal("5000000.0")
COST_FACTOR_FLOOR = Decimal("1.00")


def benefit_points(latest_warrant_score, crash_points, students_benefited,
                   referred_complaint_count):
    total = (WEIGHT_WARRANT * dec(latest_warrant_score)
             + WEIGHT_CRASH * min(CAP_CRASH_POINTS, Decimal(int(crash_points)))
             + WEIGHT_STUDENTS * min(CAP_STUDENT_POINTS,
                                     Decimal(int(students_benefited)) / STUDENTS_PER_POINT)
             + WEIGHT_COMPLAINTS * min(CAP_COMPLAINT_POINTS,
                                       COMPLAINT_POINTS_EACH * Decimal(int(referred_complaint_count))))
    return r4(total)


def cost_factor(requested_cost_cents):
    ratio = Decimal(int(requested_cost_cents)) / COST_FACTOR_DIVISOR_CENTS
    return r4(max(COST_FACTOR_FLOOR, ratio))


def benefit_cost_score(points, factor):
    return r2(dec(points) / dec(factor))


# ---------------------------------------------------------------------------
# Mode share (PRD 3.9)
# ---------------------------------------------------------------------------
def mode_share_raw_pct(survey):
    responses = (survey["walk_count"] + survey["bike_count"] + survey["bus_count"]
                 + survey["car_count"] + survey["other_count"])
    numerator = survey["walk_count"] + survey["bike_count"]
    return r2(D100 * Decimal(numerator) / Decimal(responses))


def mode_share_weighted_pct(survey):
    numerator = survey["walk_count"] + survey["bike_count"]
    return r2(D100 * Decimal(numerator) / Decimal(int(survey["enrollment_at_survey"])))


# ---------------------------------------------------------------------------
# Shift conflict (PRD 3.5) -- asymmetric
# ---------------------------------------------------------------------------
_CONFLICTS = {
    "BOTH": ("AM", "PM", "BOTH"),
    "AM": ("AM", "BOTH"),
    "PM": ("PM", "BOTH"),
}


def shifts_conflict(shift_a, shift_b):
    return shift_b in _CONFLICTS.get(shift_a, ())
