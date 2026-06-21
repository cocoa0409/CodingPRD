"""Calculation rules (PRD §3.5, §3.6 / SCAFFOLD calculations table).

All hour quantities are carried to two decimal places, rounded half up. Floats
are never used for the rounding step — Decimal with ROUND_HALF_UP is used so
ties round up deterministically.
"""
from decimal import Decimal, ROUND_HALF_UP


SECONDS_PER_DAY = 86400
NO_SHOW_PENALTY = 8

# Background-check tier ladder (PRD §3.2)
BG_TIER_RANK = {"NONE": 0, "BASIC": 1, "STANDARD": 2, "ENHANCED": 3}

# Recognition tier ladder (PRD §3.6)
MILESTONE_RANK = {"NONE": 0, "BRONZE": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 4}

# Milestone breakpoints — inclusive lower bounds (PRD §3.6)
BRONZE_AT = Decimal("25")
SILVER_AT = Decimal("100")
GOLD_AT = Decimal("200")
PLATINUM_AT = Decimal("500")


def round_half_up_2(value):
    """Round a numeric value half-up to 2 decimal places, returning a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def round_half_up_2_dec(value):
    """Round to 2dp half-up, returning a Decimal (for exact summation)."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def duration_hours(starts_at, ends_at):
    """Shift scheduled duration in hours: (ends - starts) seconds / 3600,
    rounded half up to 2dp (PRD §3.5 provisional_hours)."""
    seconds = (ends_at - starts_at).total_seconds()
    hours = Decimal(str(seconds)) / Decimal("3600")
    return round_half_up_2(hours)


def provisional_hours(starts_at, ends_at):
    """calc provisional_hours — full scheduled duration as upper-bound estimate."""
    return duration_hours(starts_at, ends_at)


def verified_hours(logged_hours, provisional):
    """calc verified_hours — min(logged, provisional) rounded half up to 2dp.

    The cap binds at the scheduled duration so verified can be strictly less than
    provisional (PRD §3.6)."""
    capped = min(Decimal(str(logged_hours)), Decimal(str(provisional)))
    return round_half_up_2(capped)


def reliability_score(verified_count, no_show_count):
    """calc reliability_score (PRD §3.5).

    V = HOURS_VERIFIED signup count, N = lifetime no-show count.
    total == 0 -> 100. else raw = 100*(V/total) - 8*N, round half up to int,
    clamp [0,100]."""
    V = int(verified_count)
    N = int(no_show_count)
    total = V + N
    if total == 0:
        return 100
    attendance_ratio = Decimal(V) / Decimal(total)
    raw = Decimal("100") * attendance_ratio - Decimal(NO_SHOW_PENALTY) * Decimal(N)
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(0, min(100, rounded))


def total_verified_hours(verified_hour_values):
    """calc milestone_total_hours (PRD §3.6).

    ROUNDING ORDER PINNED: round each per-line verified_hours to 2dp, sum those,
    then round the sum to 2dp. verified_hour_values is ordered by signup
    created_at ASC by the caller."""
    per_line = [round_half_up_2_dec(v) for v in verified_hour_values]
    total = sum(per_line, Decimal("0"))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def milestone_candidate(total_hours):
    """Candidate tier from total_verified_hours against inclusive lower bounds."""
    h = Decimal(str(total_hours))
    if h >= PLATINUM_AT:
        return "PLATINUM"
    if h >= GOLD_AT:
        return "GOLD"
    if h >= SILVER_AT:
        return "SILVER"
    if h >= BRONZE_AT:
        return "BRONZE"
    return "NONE"


def milestone_tier(current_tier, total_hours):
    """calc milestone_tier — monotonic non-decreasing max of current and the
    candidate from total_verified_hours (PRD §3.6)."""
    candidate = milestone_candidate(total_hours)
    if MILESTONE_RANK[candidate] >= MILESTONE_RANK[current_tier]:
        return candidate
    return current_tier
