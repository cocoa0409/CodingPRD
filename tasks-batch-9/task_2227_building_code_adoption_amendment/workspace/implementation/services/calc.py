"""The eleven calculations of SCAFFOLD 1.3 / PRD section 3, to the letter."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import config


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def to_float(value):
    return None if value is None else float(value)


def ceil_ratio(value, numerator, denominator):
    """Integer ceiling of value * numerator / denominator."""
    total = value * numerator
    return -((-total) // denominator)


# ---------------------------------------------------------------- calculation 2
def statewide_incremental_cost(affected_permit_count, cost_by_occupancy):
    """Occupancy-weighted permit split, then a plain cents multiply-and-sum."""
    if affected_permit_count is None:
        return None
    cost_by_occupancy = cost_by_occupancy or {}
    total = 0
    for key, share in config.OCCUPANCY_PERMIT_SHARE:
        class_permits = int(round_half_up(dec(affected_permit_count) * share, 0))
        per_permit = cost_by_occupancy.get(key)
        if per_permit is None:
            per_permit = 0
        total += class_permits * int(per_permit)
    return total


def permit_split(affected_permit_count):
    out = {}
    for key, share in config.OCCUPANCY_PERMIT_SHARE:
        out[key] = int(round_half_up(dec(affected_permit_count) * share, 0))
    return out


# ---------------------------------------------------------------- calculation 3
def preliminary_bcr(annual_cost_savings_cents, statewide_incremental_cost_cents):
    if statewide_incremental_cost_cents in (None, 0) or annual_cost_savings_cents is None:
        return None
    numerator = dec(annual_cost_savings_cents) * config.PRELIM_HORIZON_YEARS
    return round_half_up(numerator / dec(statewide_incremental_cost_cents), 2)


def annuity_factor(measure_life_years):
    rate = config.DISCOUNT_RATE
    raw = (Decimal(1) - (Decimal(1) + rate) ** (-int(measure_life_years))) / rate
    return round_half_up(raw, 6)


def final_bcr(annual_cost_savings_cents, measure_life_years, statewide_incremental_cost_cents):
    if statewide_incremental_cost_cents in (None, 0):
        return None
    if annual_cost_savings_cents is None or measure_life_years is None:
        return None
    factor = annuity_factor(measure_life_years)
    raw = dec(annual_cost_savings_cents) * factor / dec(statewide_incremental_cost_cents)
    return round_half_up(raw, 2)


# ---------------------------------------------------------------- calculation 4
def base_docket_score(support_count, oppose_count, stringency_direction,
                      statewide_incremental_cost_cents):
    decisive = support_count + oppose_count
    if decisive == 0:
        support_ratio = config.SUPPORT_RATIO_DEFAULT
    else:
        support_ratio = round_half_up(dec(support_count) / dec(decisive), 4)
    stringency_points = config.STRINGENCY_POINTS.get(stringency_direction, Decimal("0"))
    if statewide_incremental_cost_cents is None:
        cost_ratio = Decimal(1)
    else:
        cost_ratio = dec(statewide_incremental_cost_cents) / config.COST_POINTS_CAP_CENTS
        if cost_ratio > Decimal(1):
            cost_ratio = Decimal(1)
    cost_points = round_half_up(Decimal(1) - cost_ratio, 6)
    weighted = (config.WEIGHT_SUPPORT * support_ratio
                + config.WEIGHT_STRINGENCY * stringency_points
                + config.WEIGHT_COST * cost_points)
    return round_half_up(weighted * Decimal(100), 2)


def rank_adjustment(rank):
    if rank == 1:
        return config.RANK1_BONUS
    if rank == 2:
        return config.RANK2_BONUS
    return Decimal("0.00")


def docket_priority_score(base, rank):
    return round_half_up(dec(base) + rank_adjustment(rank), 2)


# ---------------------------------------------------------------- calculation 6
def quorum_required(seat_count):
    return int(ceil_ratio(int(seat_count), config.QUORUM_NUMERATOR, config.QUORUM_DENOMINATOR))


def supermajority_threshold(decisive):
    exact = config.SUPERMAJORITY_RATIO * Decimal(int(decisive))
    return int(exact.to_integral_value(rounding=ROUND_CEILING))


def tally_ballots(ballots, member_lookup, voting_seats_at_call, stringency_direction):
    yes = no = abstain = 0
    fire_service_no = False
    for ballot in ballots:
        value = ballot["ballot"]
        if value == "YES":
            yes += 1
        elif value == "NO":
            no += 1
            member = member_lookup.get(ballot["member_id"])
            if member is not None and member.get("sector") == "FIRE_SERVICE":
                fire_service_no = True
        else:
            abstain += 1
    cast_total = yes + no + abstain
    absent = max(voting_seats_at_call - cast_total, 0)
    decisive = yes + no
    if stringency_direction == "LESS_STRINGENT" and fire_service_no:
        outcome, reason = "REJECTED", "FIRE_SERVICE_VETO"
    elif yes <= no:
        outcome, reason = "REJECTED", "SIMPLE_MAJORITY_FAILED"
    elif yes < supermajority_threshold(decisive):
        outcome, reason = "REJECTED", "SUPERMAJORITY_FAILED"
    else:
        outcome, reason = "APPROVED", "MAJORITY_APPROVED"
    return {
        "yes_count": yes,
        "no_count": no,
        "abstain_count": abstain,
        "absent_count": absent,
        "cast_total": cast_total,
        "decisive": decisive,
        "outcome": outcome,
        "outcome_reason": reason,
    }


# ---------------------------------------------------------------- calculation 7
def adoption_schedule(base_date, approved_permit_backlog_count):
    backlog = int(approved_permit_backlog_count or 0)
    projected = (backlog * config.PROVISIONAL_REVIEW_WINDOW_DAYS) // config.DAYS_PER_YEAR
    if projected < config.BACKLOG_TIER_MEDIUM_MIN:
        grace = config.GRACE_DAYS_SMALL
    elif projected < config.BACKLOG_TIER_LARGE_MIN:
        grace = config.GRACE_DAYS_MEDIUM
    else:
        grace = config.GRACE_DAYS_LARGE
    notice = max(config.MIN_NOTICE_DAYS, grace)
    effective = midnight(base_date) + timedelta(days=notice)
    return {
        "projected_permit_backlog": projected,
        "transition_grace_days": grace,
        "notice_days": notice,
        "effective_date": effective,
        "transition_cutoff_date": effective,
        "prior_code_expiry_date": effective + timedelta(days=config.PRIOR_CODE_PROJECT_WINDOW_DAYS),
    }


def midnight(moment):
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------- calculation 8
def compliance_pct(numerator, official_headcount):
    if not official_headcount:
        return Decimal("0.00")
    value = round_half_up(dec(100) * dec(numerator) / dec(official_headcount), 2)
    if value > Decimal("100.00"):
        value = Decimal("100.00")
    return value


# ---------------------------------------------------------------- calculation 9
def statewide_readiness(rows):
    """rows: iterable of (population, attendance_pct as Decimal)."""
    rows = list(rows)
    if not rows:
        return Decimal("0.00")
    total_population = sum(dec(pop) for pop, _ in rows)
    if total_population == 0:
        return Decimal("0.00")
    weighted = sum(dec(pop) * dec(pct) for pop, pct in rows)
    return round_half_up(weighted / total_population, 2)
