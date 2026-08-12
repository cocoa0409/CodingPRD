"""Calculation rules per scaffold §1.3."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db

TIER_WEIGHT = {"CORE": 40, "TARGET": 25, "EXPLORATORY": 10}
EVENT_POINTS = 5
REFERRAL_POINTS = 15
PRIOR_INTERNSHIP_POINTS = 10
SCORE_CAP = 100

REGION_BASE = {"METRO": 300000, "REGIONAL": 200000, "REMOTE": 100000}
DISTANCE_BONUS_HIGH = 150000
DISTANCE_BONUS_MID = 75000
DISTANCE_HIGH_MILES = 1500
DISTANCE_MID_MILES = 500
CORE_METRO_SURCHARGE = 50000
STIPEND_CAP_CENTS = 400000

REGION_MULTIPLIER = {
    "METRO": Decimal("1.25"),
    "REGIONAL": Decimal("1.10"),
    "REMOTE": Decimal("1.00"),
}

RETURN_OFFER_THRESHOLD = Decimal("4.00")

EVALUATOR_BUFFER_MINUTES = 15


def screening_score(application, school, as_of):
    """Weighted score per screening_score calculation.

    completed_event_count = events of application.school_target_id in same season
    with status COMPLETED and end_at <= as_of.
    school tier is read as passed in (caller decides current-vs-snapshot).
    """
    tier_weight = TIER_WEIGHT[school["tier"]]
    completed_count = 0
    for ev in db.campus_events.values():
        if (
            ev["school_target_id"] == application["school_target_id"]
            and ev["season_id"] == application["season_id"]
            and ev["status"] == "COMPLETED"
            and ev["_end_at"] <= as_of
        ):
            completed_count += 1
    referral = REFERRAL_POINTS if application.get("referral_flag", False) else 0
    prior = PRIOR_INTERNSHIP_POINTS * application.get("prior_internship_count", 0)
    score = tier_weight + EVENT_POINTS * completed_count + referral + prior
    return min(SCORE_CAP, score)


def _is_business_second(dt):
    """True iff dt falls inside Mon-Fri [09:00,17:00) UTC."""
    if dt.weekday() >= 5:
        return False
    return 9 <= dt.hour < 17


def business_hours_deadline(extended_at, hours):
    """Earliest t such that count of business seconds in [extended_at, t] == hours*3600.

    Business hours: Mon-Fri [09:00:00, 17:00:00) UTC, half-open per second.
    The interval [extended_at, t] counts each whole second whose starting instant
    is a business second. We walk second-by-second over blocks for efficiency.
    """
    remaining = hours * 3600
    cur = extended_at
    # Advance second-by-second is too slow for 72h (259200 steps is fine actually).
    # But block-walk: find next business window start/end and consume blocks.
    while remaining > 0:
        if _is_business_second(cur):
            # End of this business block: today at 17:00 or weekday boundary
            block_end = cur.replace(hour=17, minute=0, second=0, microsecond=0)
            if block_end <= cur:
                block_end = cur + timedelta(seconds=1)
            avail = int((block_end - cur).total_seconds())
            take = min(avail, remaining)
            cur = cur + timedelta(seconds=take)
            remaining -= take
        else:
            # Jump to next business-second start
            cur = _next_business_start(cur)
    return cur


def _next_business_start(dt):
    """Return the next instant that begins a business second >= dt."""
    d = dt
    # If weekend, jump to Monday 09:00
    if d.weekday() >= 5:
        days_to_monday = 7 - d.weekday()
        d = (d + timedelta(days=days_to_monday)).replace(hour=9, minute=0, second=0, microsecond=0)
        return d
    # Weekday
    if d.hour < 9:
        return d.replace(hour=9, minute=0, second=0, microsecond=0)
    if d.hour >= 17:
        # next business day 09:00
        d = d + timedelta(days=1)
        while d.weekday() >= 5:
            d = d + timedelta(days=1)
        return d.replace(hour=9, minute=0, second=0, microsecond=0)
    return d


def exploding_deadline(extended_at, policy_hours, mode):
    if mode == "BUSINESS_HOURS":
        return business_hours_deadline(extended_at, policy_hours)
    # WALL_CLOCK
    return extended_at + timedelta(hours=policy_hours)


def stipend_amount(region, tier, distance_miles):
    base = REGION_BASE[region]
    if distance_miles >= DISTANCE_HIGH_MILES:
        bonus = DISTANCE_BONUS_HIGH
    elif distance_miles >= DISTANCE_MID_MILES:
        bonus = DISTANCE_BONUS_MID
    else:
        bonus = 0
    surcharge = CORE_METRO_SURCHARGE if (region == "METRO" and tier == "CORE") else 0
    return min(STIPEND_CAP_CENTS, base + bonus + surcharge)


def _round_half_up_int_cents(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def offer_total_comp(weekly_rate_cents, duration_weeks, sign_on_bonus_cents, region):
    mult = REGION_MULTIPLIER[region]
    salary = _round_half_up_int_cents(Decimal(weekly_rate_cents) * Decimal(duration_weeks) * mult)
    bonus = _round_half_up_int_cents(Decimal(sign_on_bonus_cents) * mult)
    return salary + bonus


def return_offer_decision(mid_rating, final_rating, would_rehire):
    """Weighted score = round_half_up_2dp((MID + 2*FINAL)/3). EXTENDED iff >=4.00 and would_rehire."""
    score = (Decimal(mid_rating) + Decimal(2) * Decimal(final_rating)) / Decimal(3)
    score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if score >= RETURN_OFFER_THRESHOLD and would_rehire:
        return "EXTENDED"
    return "NO_OFFER"


def conversion_rate(numerator, denominator):
    if denominator == 0:
        return 0
    r = Decimal(numerator) / Decimal(denominator)
    r = r.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(r)
