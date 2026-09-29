"""Pinned arithmetic: ages, fees, sponsorship, impact, risk, intervals."""
import re
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from core import round_half_up

# ------------------------------------------------------------------ constants
MIN_AGE_FLOOR = 50
AGE_BAND_WIDTH = 5
OPEN_BAND_FLOOR = 100
OPEN_BAND_CODE = "100+"
AGE_EXEMPT_FLOOR = 75

BASE_REGISTRATION_FEE_CENTS = 9500
DISCOUNT_TIERS = (
    (1, Decimal("0.00")),
    (3, Decimal("0.05")),
    (5, Decimal("0.12")),
    (None, Decimal("0.20")),
)
SURCHARGE_TIER_ONE_FLOOR = 25000
SURCHARGE_TIER_TWO_FLOOR = 60000
SURCHARGE_TIER_ONE_CENTS = 1500
SURCHARGE_TIER_TWO_CENTS = 4000

TIER_MULTIPLIERS = {
    "BRONZE": Decimal("1.00"),
    "SILVER": Decimal("1.05"),
    "GOLD": Decimal("1.12"),
    "PLATINUM": Decimal("1.25"),
}
ALLOCATION_BUCKETS = (
    ("VENUE_SIGNAGE", Decimal("0.40")),
    ("ATHLETE_SERVICES", Decimal("0.30")),
    ("MEDICAL_COVERAGE", Decimal("0.20")),
    ("SOCIAL_PROGRAM", Decimal("0.10")),
)

ACCOMPANYING_VISITOR_FACTOR = Fraction(18, 10)
PROJECTED_NIGHTS_PER_ATHLETE = 4
DAILY_SPEND_CENTS = 18500
ECONOMIC_MULTIPLIER = Fraction(145, 100)

AGE_POINT_FLOOR = 55
AGE_POINTS_PER_YEAR = Decimal("1.5")
AGE_POINT_CAP = Decimal("30")
BP_POINTS_ELEVATED = Decimal("12")
BP_POINTS_HIGH = Decimal("25")
BP_ELEVATED_FLOOR = 130
BP_HIGH_FLOOR = 150
HR_POINT_FLOOR = 70
HR_POINTS_PER_BPM = Decimal("0.4")
LOAD_POINTS_PER_CONTACT_ENTRY = Decimal("7")
LOAD_POINT_CAP = Decimal("20")
CARDIAC_MULTIPLIER = Decimal("1.6")
RISK_SCORE_CAP = Decimal("100.0")
RISK_BAND_RESTRICTED = Decimal("25.0")
RISK_BAND_HOLD = Decimal("60.0")

TRAVEL_BUFFER_SAME_VENUE_MINUTES = 0
TRAVEL_BUFFER_CROSS_VENUE_MINUTES = 45
PERSONNEL_DAILY_LIMIT_MINUTES = 480
ATHLETE_RECOVERY_GAP_MINUTES = 30
VILLAGE_LEAD_DAYS = 2
VILLAGE_TRAIL_DAYS = 2
MAX_REVISION_ROUNDS = 2
MAX_PROTEST_ROUNDS = 1
CARDIAC_PROTOCOL_BAND_FLOOR = 75

QUALIFICATION_PRIORITY = {
    "STATE_QUALIFIER": 1,
    "LOCAL_QUALIFIER": 2,
    "AGE_EXEMPT": 3,
    "ORGANIZER_INVITE": 4,
}

AGE_GROUP_CODE_RE = re.compile(r"^(5[0-9]|[6-9][0-9])-(5[0-9]|[6-9][0-9])$")


def valid_age_group_code(code):
    return code == OPEN_BAND_CODE or bool(AGE_GROUP_CODE_RE.match(code or ""))


# ----------------------------------------------------------------------- ages
def whole_years(born, target):
    """Calendar-year difference, reduced by one when the birthday has not landed."""
    years = target.year - born.year
    if (target.month, target.day) < (born.month, born.day):
        years -= 1
    return years


def age_band_code(basis_age):
    """None when the basis age is below the games-wide floor of 50."""
    if basis_age < MIN_AGE_FLOOR:
        return None
    if basis_age >= OPEN_BAND_FLOOR:
        return OPEN_BAND_CODE
    floor = MIN_AGE_FLOOR + AGE_BAND_WIDTH * ((basis_age - MIN_AGE_FLOOR) // AGE_BAND_WIDTH)
    return "%d-%d" % (floor, floor + AGE_BAND_WIDTH - 1)


def band_floor(age_group_code):
    if age_group_code == OPEN_BAND_CODE:
        return OPEN_BAND_FLOOR
    try:
        return int(str(age_group_code).split("-")[0])
    except (ValueError, IndexError):
        return 0


# ------------------------------------------------------------------------ fees
def discount_pct_for(entry_count):
    if entry_count <= 1:
        return DISCOUNT_TIERS[0][1]
    if entry_count <= 3:
        return DISCOUNT_TIERS[1][1]
    if entry_count <= 5:
        return DISCOUNT_TIERS[2][1]
    return DISCOUNT_TIERS[3][1]


def surcharge_for(discounted_cents):
    if discounted_cents < SURCHARGE_TIER_ONE_FLOOR:
        return 0
    if discounted_cents < SURCHARGE_TIER_TWO_FLOOR:
        return SURCHARGE_TIER_ONE_CENTS
    return SURCHARGE_TIER_TWO_CENTS


def settle_fee(entry_count, event_fees_cents):
    """The six pinned steps. Exactly one rounding step, on the discount."""
    subtotal_cents = BASE_REGISTRATION_FEE_CENTS + event_fees_cents
    pct = discount_pct_for(entry_count)
    discount_cents = int(round_half_up(Decimal(subtotal_cents) * pct, 0))
    discounted_cents = subtotal_cents - discount_cents
    surcharge_cents = surcharge_for(discounted_cents)
    fee_total_cents = discounted_cents + surcharge_cents
    breakdown = {
        "entry_count": entry_count,
        "event_fees_cents": event_fees_cents,
        "subtotal_cents": subtotal_cents,
        "discount_pct": float(pct),
        "discount_cents": discount_cents,
        "discounted_cents": discounted_cents,
        "surcharge_cents": surcharge_cents,
    }
    return fee_total_cents, breakdown


# ----------------------------------------------------------------- sponsorship
def allocate_sponsorship(pledged_cents, tier):
    """Four independent roundings, summed only afterwards."""
    multiplier = TIER_MULTIPLIERS[tier]
    allocation_map = {}
    recognized = 0
    for bucket, share in ALLOCATION_BUCKETS:
        amount = int(round_half_up(Decimal(pledged_cents) * share * multiplier, 0))
        allocation_map[bucket] = amount
        recognized += amount
    return recognized, allocation_map


# --------------------------------------------------------------------- impact
def provisional_impact(registered_heads):
    visitor_heads = Fraction(registered_heads) * ACCOMPANYING_VISITOR_FACTOR
    direct = int(
        round_half_up(
            (Fraction(registered_heads) + visitor_heads)
            * DAILY_SPEND_CENTS
            * PROJECTED_NIGHTS_PER_ATHLETE,
            0,
        )
    )
    impact = int(round_half_up(Fraction(direct) * ECONOMIC_MULTIPLIER, 0))
    return direct, impact


def final_impact(actual_heads, actual_room_nights):
    nights_per_head = Fraction(actual_room_nights, max(actual_heads, 1))
    visitor_heads = Fraction(actual_heads) * ACCOMPANYING_VISITOR_FACTOR
    direct = int(
        round_half_up(
            (Fraction(actual_heads) + visitor_heads) * DAILY_SPEND_CENTS * nights_per_head,
            0,
        )
    )
    impact = int(round_half_up(Fraction(direct) * ECONOMIC_MULTIPLIER, 0))
    return direct, impact


# -------------------------------------------------------------- medical risk
def risk_score(age_at_reference, systolic_bp, resting_hr, prior_cardiac_event, contact_sport_count):
    age_points = min(
        AGE_POINT_CAP,
        Decimal(max(0, age_at_reference - AGE_POINT_FLOOR)) * AGE_POINTS_PER_YEAR,
    )
    if systolic_bp < BP_ELEVATED_FLOOR:
        bp_points = Decimal(0)
    elif systolic_bp < BP_HIGH_FLOOR:
        bp_points = BP_POINTS_ELEVATED
    else:
        bp_points = BP_POINTS_HIGH
    hr_points = Decimal(max(0, resting_hr - HR_POINT_FLOOR)) * HR_POINTS_PER_BPM
    load_points = min(
        LOAD_POINT_CAP, Decimal(contact_sport_count) * LOAD_POINTS_PER_CONTACT_ENTRY
    )
    multiplier = CARDIAC_MULTIPLIER if prior_cardiac_event else Decimal("1.0")
    raw = (age_points + bp_points + hr_points + load_points) * multiplier
    score = round_half_up(min(RISK_SCORE_CAP, raw), 1)
    return score


def recommendation_for(score):
    if score < RISK_BAND_RESTRICTED:
        return "CLEARED"
    if score < RISK_BAND_HOLD:
        return "CLEARED_WITH_RESTRICTION"
    return "HOLD_PENDING_PHYSICIAN_REVIEW"


# ------------------------------------------------------------------ intervals
def occupied_window(start, end, buffer_minutes):
    """Venue-area footprint: start included, buffered end excluded."""
    return start, end + timedelta(minutes=buffer_minutes)


def windows_intersect(a_lo, a_hi, b_lo, b_hi):
    """Half-open intersection: touching endpoints do not collide."""
    return a_lo < b_hi and b_lo < a_hi


def personnel_collides(existing_start, existing_end, buffer_minutes, cand_start, cand_end):
    """Closed, symmetrically buffered comparison: touching blocks do collide."""
    low = existing_start - timedelta(minutes=buffer_minutes)
    high = existing_end + timedelta(minutes=buffer_minutes)
    return low <= cand_end and cand_start <= high


def gap_minutes(a_start, a_end, b_start, b_end):
    """Whole minutes from the earlier end to the later start; may be negative."""
    earlier_end = min(a_end, b_end)
    later_start = max(a_start, b_start)
    return int((later_start - earlier_end).total_seconds() // 60)


def nights_between(check_in, check_out):
    return (check_out - check_in).days


def stay_dates(check_in, check_out):
    """Every occupied night: check-in included, departure date excluded."""
    span = (check_out - check_in).days
    from datetime import timedelta as _td

    return [check_in + _td(days=offset) for offset in range(max(span, 0))]


def national_qualifying(mark_value, standard, mark_direction):
    if standard is None:
        return False
    if mark_direction == "LOWER_IS_BETTER":
        return mark_value <= standard
    return mark_value >= standard


def beats_record(mark_value, record_mark, mark_direction):
    if mark_direction == "LOWER_IS_BETTER":
        return mark_value < record_mark
    return mark_value > record_mark
