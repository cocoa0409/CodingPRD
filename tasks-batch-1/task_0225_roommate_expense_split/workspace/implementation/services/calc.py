"""Calculation rules (scaffold §1.3 / PRD §3): compatibility_score, bill_split,
move_proration, household_net_balance.

All money is whole integer cents. Proration uses round-half-up; splits use
floor-then-distribute-remainder by created_at ASC.
"""
from decimal import Decimal, ROUND_HALF_UP

# compatibility_score constants
W_CLEAN = 40
W_SLEEP = 30
W_LIFESTYLE = 30
MATCH_THRESHOLD = 60


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# compatibility_score (PRD §3.1)
# ---------------------------------------------------------------------------
def compatibility_score(profile, listing, scoring_mode):
    cleanliness_fit = max(0, 5 - abs(profile["cleanliness"] - listing["wants_cleanliness"])) / 5.0

    p_sleep = profile["sleep_schedule"]
    l_sleep = listing["wants_sleep_schedule"]
    if l_sleep == "FLEXIBLE" or p_sleep == "FLEXIBLE":
        sleep_fit = 1.0
    elif p_sleep == l_sleep:
        sleep_fit = 1.0
    else:
        sleep_fit = 0.0

    lifestyle_fit = 1.0
    smoker_break = listing["no_smokers"] and profile["smoker"]
    pet_break = listing["no_pets"] and profile["pets"]
    if smoker_break:
        lifestyle_fit -= 0.5
    if pet_break:
        lifestyle_fit -= 0.5
    lifestyle_fit = max(0.0, lifestyle_fit)

    base = (W_CLEAN * cleanliness_fit) + (W_SLEEP * sleep_fit) + (W_LIFESTYLE * lifestyle_fit)
    raw = round_half_up(base)

    any_dealbreaker = smoker_break or pet_break
    if scoring_mode == "STRICT" and any_dealbreaker:
        return 0
    return raw


# ---------------------------------------------------------------------------
# bill_split / expense waterfall (PRD §2.7, §3.4): floor-then-distribute remainder
# `entries` is a list of (key, weight) in created_at ASC order.
# Returns dict key -> share_cents.
# ---------------------------------------------------------------------------
def waterfall_allocation(total_cents, entries):
    keys = [k for k, _ in entries]
    weights = {k: w for k, w in entries}
    total_weight = sum(weights[k] for k in keys)
    if total_weight <= 0:
        # degenerate: fall back to equal weighting
        total_weight = len(keys)
        weights = {k: 1 for k in keys}

    base = {}
    for k in keys:
        base[k] = (total_cents * weights[k]) // total_weight
    assigned = sum(base.values())
    remainder = total_cents - assigned
    for i in range(remainder):
        base[keys[i]] += 1
    return base


def split_weight(policy, member_profile, listing):
    if policy == "EQUAL":
        return 1
    if policy == "BY_ROOM_SIZE":
        return listing["room_size_sqft"]
    if policy == "BY_INCOME":
        return max(1, member_profile["monthly_income_cents"])
    return 1


# ---------------------------------------------------------------------------
# move_proration (PRD §3.5): inclusive-day occupancy and round-half-up rent share
# ---------------------------------------------------------------------------
def period_days(period_start, period_end):
    return (period_end.date() - period_start.date()).days + 1


def occupied_days(move_in_date, end_candidate, period_start, period_end):
    """Inclusive occupied days within [period_start, period_end].

    end_candidate is planned_move_out_date (estimate) or actual_move_out_date (final).
    Membership dates are optional in this system; a null move_in_date defaults to the
    period start (the member is taken to occupy from the start of the period) and a null
    end_candidate defaults to the period end (occupies through the end).
    """
    move_in_d = move_in_date.date() if move_in_date is not None else period_start.date()
    end_d = end_candidate.date() if end_candidate is not None else period_end.date()
    est_start = max(move_in_d, period_start.date())
    eff_end = min(end_d, period_end.date())
    if eff_end < est_start:
        return 0
    return max(0, (eff_end - est_start).days + 1)


def prorated_share(full_share_cents, occupied, total_period_days):
    if total_period_days <= 0:
        return 0
    return round_half_up(Decimal(full_share_cents * occupied) / Decimal(total_period_days))


def intervals_overlap(a_in, a_out, b_in, b_out):
    """Half-open occupancy overlap (PRD §3.3, validation priority 13).

    Two intervals [move_in, planned_move_out) overlap iff
      a_in < b_out AND b_in < a_out (touching endpoints do not overlap).
    Membership dates are optional; a null start is treated as -infinity and a null
    end as +infinity, so an undated membership is open-ended and overlaps any other
    undated/dated membership on the same single-occupancy room.
    """
    a_in_d = a_in.date() if a_in is not None else None
    a_out_d = a_out.date() if a_out is not None else None
    b_in_d = b_in.date() if b_in is not None else None
    b_out_d = b_out.date() if b_out is not None else None

    # a_in < b_out
    cond1 = (a_in_d is None) or (b_out_d is None) or (a_in_d < b_out_d)
    # b_in < a_out
    cond2 = (b_in_d is None) or (a_out_d is None) or (b_in_d < a_out_d)
    return cond1 and cond2
