"""Lane data quality, the lane baseline and the event-level rollups —
PRD §3.3."""
from decimal import Decimal

import store
from numeric import D, q2

# --- data-quality constants (PRD §3.3) --------------------------------------
MILEAGE_MIN = 25
MILEAGE_MAX = 3200
VOLUME_VARIANCE_TOLERANCE_PCT = Decimal("25.00")
SEASONALITY_EXTREME_INDEX = Decimal("1.50")
ACCESSORIAL_OUTLIER_RATIO = Decimal("0.10")

BLOCKING_FLAGS = ("MILEAGE_IMPLAUSIBLE", "MISSING_TRAILING_VOLUME")

# Lane statuses that are inside the event's procurement scope.
SCOPE_LANE_STATUSES = ("VALIDATED", "LOCKED", "AWARDED", "UNDER_REBID")
# Allocation statuses that hold lane volume (PRD §2.12).
HOLDING_ALLOCATION_STATUSES = ("APPROVED", "EXECUTED", "ACTIVE", "SUSPENDED_ROUTING")
# Contract statuses that contribute to the event's award cost (PRD §3.3).
AWARD_COST_CONTRACT_STATUSES = ("DRAFT", "EXECUTED", "AMENDED")


def data_quality_flags(lane):
    """Recomputed from scratch every time; the list is replaced wholesale and the flags
    are emitted in exactly the declared order, with no sorting and no de-duplication."""
    flags = []
    mileage = lane["mileage"]
    if mileage < MILEAGE_MIN or mileage > MILEAGE_MAX:
        flags.append("MILEAGE_IMPLAUSIBLE")

    trailing = lane["trailing_12m_actual_loads"]
    if trailing is None or trailing == 0:
        flags.append("MISSING_TRAILING_VOLUME")

    if trailing is not None and trailing > 0:
        planned = lane["annual_volume_loads"]
        variance = q2(abs(D(planned) - D(trailing)) * Decimal("100.00") / D(planned))
        if variance > VOLUME_VARIANCE_TOLERANCE_PCT:
            flags.append("VOLUME_VARIANCE_HIGH")

    if D(lane["seasonality_peak_index"]) >= SEASONALITY_EXTREME_INDEX:
        flags.append("SEASONALITY_EXTREME")

    if lane["incumbent_carrier_id"] is None or lane["incumbent_rate_per_mile"] is None:
        flags.append("NO_INCUMBENT_BASELINE")

    if lane["incumbent_rate_per_mile"] is not None:
        linehaul = q2(D(mileage) * D(lane["incumbent_rate_per_mile"]))
        threshold = q2(linehaul * ACCESSORIAL_OUTLIER_RATIO)
        if D(lane["accessorial_history_usd_per_load"]) > threshold:
            flags.append("ACCESSORIAL_OUTLIER")

    return flags


def refresh_flags(lane):
    lane["data_quality_flags"] = data_quality_flags(lane)
    return lane["data_quality_flags"]


def has_blocking_flag(lane):
    return any(flag in BLOCKING_FLAGS for flag in lane["data_quality_flags"])


def baseline_cost(lane):
    """Three rounding steps taken in order; none may be collapsed into the others.
    With no incumbent rate the baseline is 0.00 outright, and the inflation factor never
    touches it."""
    rate = lane["incumbent_rate_per_mile"]
    if rate is None:
        return Decimal("0.00")
    linehaul = q2(D(lane["mileage"]) * D(rate))
    per_load = q2(linehaul + D(lane["accessorial_history_usd_per_load"]))
    return q2(per_load * D(lane["annual_volume_loads"]))


def event_lanes(event_id):
    return store.sorted_rows([l for l in store.lanes.values()
                              if l["bid_event_id"] == event_id])


def scope_lanes(event_id):
    return [l for l in event_lanes(event_id) if l["status"] in SCOPE_LANE_STATUSES]


def event_allocations(event_id):
    return store.sorted_rows([a for a in store.allocations.values()
                              if a["bid_event_id"] == event_id])


def recompute_lane_count(event):
    event["lane_count"] = len(event_lanes(event["id"]))


def recompute_awarded_coverage(lane):
    """annual minus unallocated, over annual, as a percentage."""
    annual = D(lane["annual_volume_loads"])
    if annual == 0:
        lane["awarded_coverage_pct"] = Decimal("0.00")
        return
    held = annual - D(lane["unallocated_volume_loads"])
    lane["awarded_coverage_pct"] = q2(held * Decimal("100.00") / annual)


def recompute_scope(event):
    """total_scope_volume_loads and baseline_cost_usd, each reading its own status set.
    A lane flagged NO_INCUMBENT_BASELINE contributes nothing to the baseline, so it can
    never manufacture apparent savings."""
    lanes = scope_lanes(event["id"])
    event["total_scope_volume_loads"] = sum(l["annual_volume_loads"] for l in lanes)
    total = Decimal("0")
    for lane in lanes:
        if "NO_INCUMBENT_BASELINE" in lane["data_quality_flags"]:
            continue
        total += D(lane["baseline_cost_usd"] or 0)
    event["baseline_cost_usd"] = q2(total)


def recompute_award_cost(event):
    """award_cost_usd is 0.00 when the event has no contracts at all; otherwise it sums
    the committed value of its DRAFT, EXECUTED and AMENDED contracts.  savings_pct may
    legitimately be negative and is never clamped."""
    contracts = [c for c in store.contracts.values() if c["bid_event_id"] == event["id"]]
    if not contracts:
        event["award_cost_usd"] = Decimal("0.00")
    else:
        total = Decimal("0")
        for contract in contracts:
            if contract["status"] in AWARD_COST_CONTRACT_STATUSES:
                total += D(contract["total_committed_value_usd"] or 0)
        event["award_cost_usd"] = q2(total)

    baseline = D(event["baseline_cost_usd"] or 0)
    award = D(event["award_cost_usd"] or 0)
    if baseline == 0 or award == 0:
        event["savings_pct"] = Decimal("0.00")
    else:
        event["savings_pct"] = q2((baseline - award) * Decimal("100.00") / baseline)


def recompute_coverage(event):
    """coverage_pct and diversity_pct, both volume-weighted over the holding statuses."""
    allocated = 0
    diverse = 0
    for allocation in event_allocations(event["id"]):
        if allocation["status"] not in HOLDING_ALLOCATION_STATUSES:
            continue
        volume = allocation["allocated_volume_loads"]
        allocated += volume
        carrier = store.carriers.get(allocation["carrier_id"])
        if carrier and carrier["diversity_classification"] != "NONE":
            diverse += volume

    scope = event["total_scope_volume_loads"]
    if not scope:
        event["coverage_pct"] = Decimal("0.00")
    else:
        event["coverage_pct"] = q2(D(allocated) * Decimal("100.00") / D(scope))

    if allocated == 0:
        event["diversity_pct"] = Decimal("0.00")
    else:
        event["diversity_pct"] = q2(D(diverse) * Decimal("100.00") / D(allocated))
