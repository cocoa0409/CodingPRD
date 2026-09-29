"""The thirteen calculations. All rounding is half up on the magnitude."""
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# constants pinned by the specification
# ---------------------------------------------------------------------------
HANDICAP_VALIDITY_DAYS = 180
ENTRY_LATE_WINDOW_HOURS = 72
LATE_SURCHARGE_PCT = Decimal("0.10")
ASSISTANCE_STANDARD_FEE_CENTS = 25000
PER_MEMBER_CAP_CENTS = 60000
ROUND_DISPUTE_LIMIT = 3
RULES_REOPEN_WINDOW_HOURS = 48
RULES_APPEAL_WINDOW_HOURS = 72
CONDUCT_APPEAL_WINDOW_DAYS = 14
CONDUCT_WINDOW_DAYS = 365
COACH_GRANT_TERM_DAYS = 180
LATE_WD_DEMOTION_THRESHOLD = 2
UNRANKED_SORT_RANK = 999999
STANDARD_SLOPE = 113
PACE_FREE_WARNINGS = 2
PACE_TIMING_THRESHOLD_MINUTES = 15
PACE_TIMING_STROKES = 2
PACE_PENALTY_CAP = 3
FIELD_QUALITY_CAP = Decimal("1.60")
FIELD_QUALITY_BASE = Decimal("1.00")
TOP_RANK_THRESHOLD = 50
FIELD_DEPTH_FREE = 12
CERTIFIED_COUNTED_MIN_DIVISOR = 4
DIFFERENTIAL_PAR_REFERENCE = Decimal("2.0")
DIFFERENTIAL_POINTS_PER_STROKE = Decimal("25")
FINISH_FACTOR_DECAY = Decimal("0.05")
FINISH_FACTOR_FLOOR = Decimal("0.20")
SUSPENSION_POINTS_THRESHOLD = 6
VENUE_BAN_POINTS_THRESHOLD = 3

TIER_BASE_POINTS = {
    "LOCAL": Decimal("150"),
    "REGIONAL": Decimal("300"),
    "NATIONAL": Decimal("600"),
    "INVITATIONAL": Decimal("800"),
}

CONDUCT_POINTS_BY_CODE = {
    "SPECTATOR_INTERFERENCE": 2,
    "COACHING_VIOLATION": 2,
    "ABUSIVE_LANGUAGE": 3,
    "CADDIE_ADVICE_BREACH": 2,
    "PHYSICAL_ALTERCATION": 6,
    "SCORE_TAMPERING": 6,
}

SLOT_HOLDING_STATUSES = ("ACCEPTED", "COMPETING", "FINISHED", "DISQUALIFIED")
LIVE_AID_STATUSES = ("APPLIED", "ACCEPTED", "WAITLISTED", "COMPETING")
CLOSED_STATUSES = ("WITHDRAWN", "FORFEITED", "REJECTED", "CANCELLED")

AGE_DIVISIONS = ("U13", "U15", "U17", "U19")
TIERS = ("LOCAL", "REGIONAL", "NATIONAL", "INVITATIONAL")


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rh(value, places):
    """Round half up on the magnitude (exact halves move away from zero)."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rh(value, 0))


def f2(value):
    return float(rh(value, 2))


def f1(value):
    return float(rh(value, 1))


# ---------------------------------------------------------------------------
# 1. member_age_division
# ---------------------------------------------------------------------------
def age_at_cutoff(birth_date, cutoff_date):
    years = cutoff_date.year - birth_date.year
    if (birth_date.month, birth_date.day) > (cutoff_date.month, cutoff_date.day):
        years -= 1
    return years


def age_division(age):
    if age <= 10:
        return None
    if age <= 13:
        return "U13"
    if age <= 15:
        return "U15"
    if age <= 17:
        return "U17"
    if age <= 19:
        return "U19"
    return None


# ---------------------------------------------------------------------------
# 2. tournament_field_quality_factor
# ---------------------------------------------------------------------------
def field_quality_factor(field_entries):
    field_n = len(field_entries)
    top_n = 0
    for entry in field_entries:
        rank = entry.get("rank_at_entry")
        if rank is not None and rank <= TOP_RANK_THRESHOLD:
            top_n += 1
    raw = (
        FIELD_QUALITY_BASE
        + Decimal("0.02") * top_n
        + Decimal("0.01") * max(0, field_n - FIELD_DEPTH_FREE)
    )
    return f2(min(FIELD_QUALITY_CAP, raw))


# ---------------------------------------------------------------------------
# 3. entry_priority_key
# ---------------------------------------------------------------------------
def priority_band(member, grant):
    if member["late_withdrawal_count"] >= LATE_WD_DEMOTION_THRESHOLD:
        return 2
    if grant is not None and grant["status"] == "ACTIVE":
        return 0
    if member["certified_rank_position"] is not None:
        return 1
    return 2


def priority_sort_key(entry):
    rank = entry.get("rank_at_entry")
    return (
        entry["priority_band"],
        UNRANKED_SORT_RANK if rank is None else rank,
        entry["submitted_at"] or "",
        entry["created_at"],
        entry["_seq"],
    )


# ---------------------------------------------------------------------------
# 4. entry_fee_settlement helpers
# ---------------------------------------------------------------------------
def late_surcharge(gross_fee_cents, is_late):
    if not is_late:
        return 0
    return cents(D(gross_fee_cents) * LATE_SURCHARGE_PCT)


def net_fee_due(gross_fee_cents, surcharge_cents, award_cents):
    return max(0, gross_fee_cents + surcharge_cents - award_cents)


def fee_status_after_settlement(award_cents, net_cents):
    if award_cents > 0 and net_cents == 0:
        return "AID_COVERED"
    if award_cents > 0:
        return "AID_PARTIAL"
    return "UNPAID"


# ---------------------------------------------------------------------------
# 5. assistance_award_amount
# ---------------------------------------------------------------------------
def income_per_dependent(household_income_cents, dependents):
    return int(household_income_cents // dependents)


def covered_pct(income_per_dependent_cents):
    if income_per_dependent_cents <= 1500000:
        return Decimal("1.00")
    if income_per_dependent_cents <= 2500000:
        return Decimal("0.90")
    if income_per_dependent_cents <= 4500000:
        return Decimal("0.65")
    if income_per_dependent_cents <= 7000000:
        return Decimal("0.40")
    return Decimal("0.00")


def estimated_award(pct):
    return cents(D(pct) * ASSISTANCE_STANDARD_FEE_CENTS)


def settlement_award(pct, gross_fee_cents, cap_cents, consumed_cents):
    gross_award = cents(D(pct) * gross_fee_cents)
    remaining = cap_cents - consumed_cents
    return min(gross_award, remaining)


# ---------------------------------------------------------------------------
# 6. round_pace_penalty
# ---------------------------------------------------------------------------
def pace_penalty(pace_warning_count, max_minutes_behind):
    warning_component = max(0, pace_warning_count - PACE_FREE_WARNINGS)
    timing_component = (
        PACE_TIMING_STROKES
        if max_minutes_behind >= PACE_TIMING_THRESHOLD_MINUTES
        else 0
    )
    return min(PACE_PENALTY_CAP, warning_component + timing_component)


# ---------------------------------------------------------------------------
# 7. round_scoring_differential
# ---------------------------------------------------------------------------
def adjusted_gross(gross_strokes, pace_penalty_strokes, rules_penalty_strokes):
    if gross_strokes is None:
        return None
    return gross_strokes + pace_penalty_strokes + rules_penalty_strokes


def scoring_differential(adjusted, course_rating, slope_rating):
    if adjusted is None:
        return None
    value = (D(adjusted) - D(course_rating)) * D(STANDARD_SLOPE) / D(slope_rating)
    return f1(value)


def average_differential(values):
    """Mean of already-rounded per-round differentials, rounded again to 1dp."""
    kept = [v for v in values if v is not None]
    if not kept:
        return None
    total = sum((D(v) for v in kept), Decimal("0"))
    return f1(total / D(len(kept)))


# ---------------------------------------------------------------------------
# 9. entry_event_points
# ---------------------------------------------------------------------------
def finish_factor(finish_position):
    raw = Decimal("1.00") - FINISH_FACTOR_DECAY * (finish_position - 1)
    return rh(max(FINISH_FACTOR_FLOOR, raw), 2)


def differential_bonus(avg_scoring_differential):
    if avg_scoring_differential is None:
        return Decimal("0.00")
    product = (
        DIFFERENTIAL_PAR_REFERENCE - D(avg_scoring_differential)
    ) * DIFFERENTIAL_POINTS_PER_STROKE
    return max(Decimal("0.00"), rh(product, 2))


def event_points(tier, factor, position, avg_diff):
    base = TIER_BASE_POINTS[tier]
    ff = finish_factor(position)
    bonus = differential_bonus(avg_diff)
    return f2(base * D(factor) * ff + bonus)


# ---------------------------------------------------------------------------
# 10. member_ranking_points
# ---------------------------------------------------------------------------
def provisional_points(event_point_values):
    count = len(event_point_values)
    total = sum((D(v) for v in event_point_values), Decimal("0"))
    return f2(total / D(max(1, count)))


def certified_points(event_point_values):
    count = len(event_point_values)
    total = sum((D(v) for v in event_point_values), Decimal("0"))
    divisor = max(count, CERTIFIED_COUNTED_MIN_DIVISOR)
    return f2(total / D(divisor))


# ---------------------------------------------------------------------------
# 11. conduct_sanction_tier
# ---------------------------------------------------------------------------
def sanction_tier(cumulative_points):
    if cumulative_points < VENUE_BAN_POINTS_THRESHOLD:
        return "WARNING"
    if cumulative_points < SUSPENSION_POINTS_THRESHOLD:
        return "VENUE_BAN_ONE_EVENT"
    return "MEMBER_SUSPENSION"
