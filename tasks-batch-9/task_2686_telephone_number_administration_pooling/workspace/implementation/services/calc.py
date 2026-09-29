"""The calculation catalogue (PRD 2.6 and section 3)."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import db, dec, r2
from services import constants as C
from services import core


# --------------------------------------------------------------------------
# utilization percentages (PRD 3.3)
# --------------------------------------------------------------------------

def utilization_denominator(blocks_held, administrative, aging):
    return blocks_held * C.NUMBERS_PER_BLOCK - administrative - aging


def utilization_pct(numerator, denominator):
    if denominator <= 0:
        return Decimal("0.00")
    value = dec(numerator) * Decimal(100) / dec(denominator)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def claimed_utilization(filing):
    denominator = utilization_denominator(
        filing["blocks_held_at_period_end"],
        filing["numbers_administrative"],
        filing["numbers_aging"],
    )
    numerator = (
        filing["numbers_assigned"]
        + filing["numbers_intermediate"]
        + filing["numbers_reserved"]
    )
    return utilization_pct(numerator, denominator)


def strict_utilization(filing):
    denominator = utilization_denominator(
        filing["blocks_held_at_period_end"],
        filing["numbers_administrative"],
        filing["numbers_aging"],
    )
    return utilization_pct(filing["numbers_assigned"], denominator)


def adjusted_utilization(filing, adjusted_assigned, adjusted_administrative):
    administrative = (
        adjusted_administrative
        if adjusted_administrative is not None
        else filing["numbers_administrative"]
    )
    denominator = utilization_denominator(
        filing["blocks_held_at_period_end"], administrative, filing["numbers_aging"]
    )
    return utilization_pct(adjusted_assigned, denominator)


# --------------------------------------------------------------------------
# months to exhaust (PRD 3.4)
# --------------------------------------------------------------------------

def monthly_demand_forward(filing):
    if filing is None:
        return Decimal(0)
    forecast = filing.get("forecast_quarters") or [0, 0, 0, 0]
    total = dec(forecast[0] + forecast[1]) if len(forecast) >= 2 else Decimal(0)
    return total / dec(C.DEMAND_HORIZON_MONTHS)


def monthly_demand_chronological(carrier_id, rate_center_id):
    rows = core.chronological_filings(carrier_id, rate_center_id)
    if len(rows) < 2:
        return Decimal(0)
    latest = rows[-1]
    previous = rows[-2]
    delta = dec(latest["numbers_assigned"] - previous["numbers_assigned"])
    return delta / dec(C.DEMAND_HORIZON_MONTHS)


def months_to_exhaust(rate_center, monthly_demand):
    available_numbers = dec(core.rc_available_count(rate_center["id"]) * C.NUMBERS_PER_BLOCK)
    if monthly_demand <= 0:
        return C.EXHAUST_SENTINEL_MONTHS
    return (available_numbers / monthly_demand).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def snapshot_months_to_exhaust(carrier_id, rate_center, request_type):
    """Filing-time snapshot variant selection (PRD 3.4)."""
    if request_type == "SAFETY_VALVE":
        demand = monthly_demand_chronological(carrier_id, rate_center["id"])
    else:
        demand = monthly_demand_forward(
            core.effective_filing(carrier_id, rate_center["id"])
        )
    return months_to_exhaust(rate_center, demand)


def gate_months_to_exhaust(carrier_id, rate_center):
    """Review-time gate variant selection (PRD 3.4)."""
    filing = core.effective_filing(carrier_id, rate_center["id"])
    forecast = (filing.get("forecast_quarters") if filing else None) or []
    forecast_absent = len(forecast) == 0 or all(int(q) == 0 for q in forecast)
    history = core.chronological_filings(carrier_id, rate_center["id"])
    if forecast_absent and len(history) >= 2:
        demand = monthly_demand_chronological(carrier_id, rate_center["id"])
    else:
        demand = monthly_demand_forward(filing)
    return months_to_exhaust(rate_center, demand)


# --------------------------------------------------------------------------
# the pool draw (PRD 3.5)
# --------------------------------------------------------------------------

def pool_precandidates(rate_center):
    return [
        b
        for b in core.blocks_of_rate_center(rate_center["id"])
        if b["allocation_status"] == "POOL_AVAILABLE"
        and b["routing_status"] in ("UNROUTED", "ROUTING_WITHDRAWN")
    ]


def block_pool_selection(rate_center, count=None):
    pooled = rate_center["pooling_status"] == "POOLED"
    candidates = []
    for block in pool_precandidates(rate_center):
        if not core.is_pooling_eligible(block):
            continue
        if not pooled and block["contaminated_count"] != 0:
            continue
        candidates.append(block)
    candidates.sort(
        key=lambda b: (
            b["contaminated_count"],
            b["nxx_code"],
            b["thousands_digit"],
            b["created_at"],
            b["_seq"],
        )
    )
    if count is None:
        return candidates
    return candidates[:count]


# --------------------------------------------------------------------------
# entitlement (PRD 3.5)
# --------------------------------------------------------------------------

def utilization_tier_cap(utilization):
    if utilization >= C.UTILIZATION_TIER_3_PCT:
        return 3
    if utilization >= C.UTILIZATION_TIER_2_PCT:
        return 2
    if utilization >= C.UTILIZATION_MIN_PCT_GROWTH:
        return 1
    return 0


def demand_ceiling(filing):
    if filing is None:
        return 0
    forecast = filing.get("forecast_quarters") or [0, 0, 0, 0]
    total = forecast[0] + forecast[1] if len(forecast) >= 2 else 0
    if total <= 0:
        return 0
    return -((-total) // C.NUMBERS_PER_BLOCK)


def growth_grant_size(request, rate_center):
    """Returns the four ceilings and the entitlement (PRD 3.5)."""
    carrier_id = request["carrier_id"]
    filing = core.effective_filing(carrier_id, rate_center["id"])
    utilization = core.effective_utilization(carrier_id, rate_center["id"])
    tier_cap = utilization_tier_cap(utilization)
    demand = demand_ceiling(filing)
    request_type = request["request_type"]
    if request_type == "INITIAL":
        tier_cap = 1
        demand = 1
    elif request_type == "SAFETY_VALVE":
        tier_cap = 1
        demand = 1
    elif request_type == "POOL_REPLENISH" and rate_center["pooling_status"] == "POOLED":
        tier_cap = tier_cap + 1
    candidates = block_pool_selection(rate_center)
    pool_ceiling = len(candidates)
    entitlement = min(request["requested_block_count"], demand, tier_cap, pool_ceiling)
    return {
        "utilization": utilization,
        "tier_cap": tier_cap,
        "demand_ceiling": demand,
        "pool_ceiling": pool_ceiling,
        "entitlement": entitlement,
        "candidates": candidates,
    }


# --------------------------------------------------------------------------
# donation obligation (PRD 3.6)
# --------------------------------------------------------------------------

def donation_rate(utilization):
    if utilization >= C.UTILIZATION_TIER_3_PCT:
        return C.DONATION_RATE_90
    if utilization >= C.UTILIZATION_TIER_2_PCT:
        return C.DONATION_RATE_75
    if utilization >= C.UTILIZATION_MIN_PCT_GROWTH:
        return C.DONATION_RATE_60
    return C.DONATION_RATE_BELOW_60


def donation_obligation(blocks_held, utilization):
    rate = donation_rate(utilization)
    return int((dec(blocks_held) * rate).to_integral_value(rounding=ROUND_FLOOR))


def donation_candidates(carrier_id, rate_center_id):
    rows = [
        b
        for b in core.blocks_of_rate_center(rate_center_id)
        if b.get("holder_carrier_id") == carrier_id
        and b["allocation_status"] in ("RESERVED", "ASSIGNED")
        and core.is_pooling_eligible(b)
        and b["routing_status"] in ("UNROUTED", "ROUTING_WITHDRAWN")
    ]
    rows.sort(key=lambda b: (-b["contaminated_count"], b["created_at"], b["_seq"]))
    return rows


# --------------------------------------------------------------------------
# weighted comment tally (PRD 3.9)
# --------------------------------------------------------------------------

def comment_tally(plan_id):
    overlay_raw = Decimal(0)
    split_raw = Decimal(0)
    total = 0
    for comment in db.comments.values():
        if comment["relief_plan_id"] != plan_id:
            continue
        total += 1
        weight = dec(comment["weight"])
        if comment["position"] == "SUPPORT_OVERLAY":
            overlay_raw += weight
        elif comment["position"] == "SUPPORT_SPLIT":
            split_raw += weight
    recommendation = (
        "GEOGRAPHIC_SPLIT" if split_raw > overlay_raw else "ALL_SERVICES_OVERLAY"
    )
    return {
        "overlay_weight": r2(overlay_raw),
        "split_weight": r2(split_raw),
        "comment_count": total,
        "recommendation": recommendation,
    }


# --------------------------------------------------------------------------
# audit penalty (PRD 3.3)
# --------------------------------------------------------------------------

def audit_penalty_action(finding_type, claimed_pct, adjusted_pct):
    if finding_type == "NO_DISCREPANCY":
        return "NONE"
    if finding_type == "MISSING_DATA":
        return "PROBATION"
    delta = abs(dec(claimed_pct or 0) - dec(adjusted_pct or 0))
    if delta >= C.AUDIT_DELTA_REFERRAL_PCT:
        return "RECLAMATION_REFERRAL"
    if delta >= C.AUDIT_DELTA_PROBATION_PCT:
        return "PROBATION"
    return "NONE"
