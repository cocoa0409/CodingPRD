"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3.3-§3.7).

All money is integer cents; contingency is 7.5% rounded half-up to a whole
cent PER REQUEST/PLAN before any summation (PRD §2.6). Speeds round half-up
to 1 dp; volumes to whole vehicles; reductions to 1 dp. Snapshot thresholds
are ceilings of exact products; ballot outcomes use integer cross-multiplication.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

CONTINGENCY_RATE = Decimal("0.075")          # PRD §2.6
PETITION_NUM, PETITION_DEN = 60, 100         # petition ratio 0.60 (exact)
QUORUM_NUM, QUORUM_DEN = 25, 100             # quorum ratio 0.25 (exact)
SCORE_ELIGIBILITY_THRESHOLD = 60             # inclusive (PRD §3.3)
SCORE_CAP = 100
STUDY_GAP_DAYS = 7                           # inclusive buffer (PRD §3.3)
P85_REDUCTION_TARGET = Decimal("3.0")        # official verdict (PRD §3.8)
MEAN_REDUCTION_TARGET = Decimal("2.0")       # advisory variant (PRD §3.8)
MIN_OBSERVATION_DAYS = 3


def round_half_up_1(x):
    """Round half-up to 1 decimal place."""
    return Decimal(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round_half_up_int(x):
    """Round half-up to a whole integer."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_ratio(n, num, den):
    """Ceiling of the exact product n * num/den (never pre-rounded)."""
    return -(-(n * num) // den)


def required_signatures(household_count):
    return ceil_ratio(household_count, PETITION_NUM, PETITION_DEN)


def quorum_required(eligible_households):
    return ceil_ratio(eligible_households, QUORUM_NUM, QUORUM_DEN)


def contingency_cents(base_cents):
    """7.5% of base, rounded half-up to a whole cent BEFORE summing."""
    return int((Decimal(base_cents) * CONTINGENCY_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def allocation_for(base_cents):
    return base_cents + contingency_cents(base_cents)


def aggregates(observations):
    """PRD §3.3 study_aggregation over the given observation set.
    Returns (p85_mph Decimal 1dp, mean_speed_mph Decimal 1dp, adv int)."""
    n = len(observations)
    p85 = round_half_up_1(sum(o["p85_speed_mph"] for o in observations) / Decimal(n))
    mean = round_half_up_1(sum(o["mean_speed_mph"] for o in observations) / Decimal(n))
    adv = round_half_up_int(Decimal(sum(o["vehicle_count"] for o in observations)) / Decimal(n))
    return p85, mean, adv


def criteria_score(p85_mph, avg_daily_volume, segment):
    """PRD §3.3 weighted scoring against the request's segment."""
    excess = p85_mph - Decimal(segment["speed_limit_mph"])
    if excess < 0:
        excess = Decimal(0)
    if excess >= 10:
        speed_points = 40
    elif excess >= 7:
        speed_points = 30
    elif excess >= 4:
        speed_points = 20
    elif excess >= 1:
        speed_points = 10
    else:
        speed_points = 0
    if avg_daily_volume >= 3000:
        volume_points = 20
    elif avg_daily_volume >= 2000:
        volume_points = 15
    elif avg_daily_volume >= 1000:
        volume_points = 10
    else:
        volume_points = 0
    crash_points = min(3, segment["crash_count_3yr"]) * 5
    pedestrian_points = min(2, segment["pedestrian_generator_count"]) * 10
    return min(SCORE_CAP, speed_points + volume_points + crash_points + pedestrian_points)


def study_window_conflicts(new_start, new_end, existing):
    """PRD §3.3: inclusive 7-day buffer in both directions.
    Conflict iff new.start <= s.end + 7d AND s.start - 7d <= new.end."""
    for s in existing:
        if new_start <= s["window_end_date"] + timedelta(days=STUDY_GAP_DAYS) and \
           s["window_start_date"] - timedelta(days=STUDY_GAP_DAYS) <= new_end:
            return True
    return False


def crew_conflict(crew_ref, new_start, duration_days, work_orders, exclude_id=None):
    """PRD §3.7: half-open [start, start+duration) overlap; adjacency allowed."""
    new_end = new_start + timedelta(days=duration_days)
    for w in work_orders:
        if w["id"] == exclude_id:
            continue
        if w["crew_ref"] != crew_ref or w["schedule_status"] != "SCHEDULED":
            continue
        w_start = w["scheduled_date"]
        w_end = w_start + timedelta(days=w["duration_days"])
        if new_start < w_end and w_start < new_end:
            return True
    return False


def ballot_outcome(votes_received, votes_for, quorum):
    """PRD §3.6: integer cross-multiplication; exact 60% passes; zero votes deny."""
    return votes_received >= quorum and 100 * votes_for >= 60 * votes_received
