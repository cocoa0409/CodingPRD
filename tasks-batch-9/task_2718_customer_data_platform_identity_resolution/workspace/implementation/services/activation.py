"""Activation scheduling guards, dispatch/resume resolution and match reporting."""

from datetime import timedelta
from decimal import Decimal

import db
from services import calc, cascade, derive


# ------------------------------------------------------- scheduling guards

def _same_destination(destination_id, exclude_id=None):
    return [
        a for a in db.by_seq(db.all_of("activations"))
        if a["destination_id"] == destination_id and a["id"] != exclude_id
    ]


def _intersects(a_start, a_end, b_start, b_end):
    """Closed intervals: touching at a single instant counts as intersecting."""
    return a_start <= b_end and b_start <= a_end


def cooldown_violation(destination, window_start, window_end, exclude_id=None):
    gap = timedelta(minutes=destination["cooldown_minutes"])
    for other in _same_destination(destination["id"], exclude_id):
        if other["status"] == "TERMINATED":
            continue
        other_start = other["window_start_at"]
        other_end = other["window_end_at"]
        if _intersects(window_start, window_end, other_start, other_end):
            continue
        if window_start >= other_end + gap:
            continue
        if other_start >= window_end + gap:
            continue
        return True
    return False


def concurrency_violation(destination, window_start, window_end, exclude_id=None):
    windows = [(window_start, window_end)]
    for other in _same_destination(destination["id"], exclude_id):
        if other["status"] not in derive.OCCUPYING_ACTIVATION_STATUSES:
            continue
        windows.append((other["window_start_at"], other["window_end_at"]))
    cap = destination["max_concurrent_activations"]
    for instant, _end in windows:
        covering = sum(1 for start, end in windows if start <= instant <= end)
        if covering > cap:
            return True
    return False


# ---------------------------------------------------- dispatch and resume

def apply_resolution(activation, segment, destination):
    counts = cascade.resolve_audience(segment, destination)
    activation["candidate_count"] = counts["candidate_count"]
    activation["audience_size"] = counts["audience_size"]
    activation["suppressed_count"] = counts["suppressed_count"]
    activation["dispatched_hash_count"] = counts["dispatched_hash_count"]
    return counts


def dispatch(activation, segment, destination):
    activation["status"] = "DISPATCHED"
    activation["dispatched_at"] = db.now()
    activation["paused_reason"] = None
    destination["remaining_daily_hash_quota"] -= activation["dispatched_hash_count"]
    db.touch(activation)
    db.touch(destination)
    db.touch(segment)
    return activation


def resume(activation, segment, destination):
    activation["status"] = "ACTIVE"
    activation["paused_reason"] = None
    destination["remaining_daily_hash_quota"] -= activation["dispatched_hash_count"]
    db.touch(activation)
    db.touch(destination)
    db.touch(segment)
    return activation


def pause(activation, segment, destination, reason):
    activation["status"] = "PAUSED"
    activation["paused_reason"] = reason
    destination["remaining_daily_hash_quota"] += activation["dispatched_hash_count"]
    db.touch(activation)
    db.touch(destination)
    db.touch(segment)
    cascade.governance_hop(segment)
    return activation


# -------------------------------------------------------- match reporting

def report(activation, destination, matched, unusable, conversions):
    activation["vendor_matched_count"] = matched
    activation["unusable_hash_count"] = unusable
    gross, net = calc.match_rates(activation["dispatched_hash_count"], matched, unusable)
    activation["gross_match_rate"] = gross
    activation["net_match_rate"] = net
    effective = gross if destination["match_rate_basis"] == "GROSS" else net
    activation["effective_match_rate"] = effective
    floor = calc.dec(destination["min_match_rate"])
    activation["status"] = "ACTIVE" if effective >= floor else "UNDERPERFORMING"

    touched_profiles = {}
    touched_households = {}
    for conversion in conversions:
        activation["attributed_conversions"].append(conversion)
        profile = db.store["profiles"].get(conversion["profile_id"])
        if profile is None:
            continue
        profile["lifetime_value_cents"] += conversion["revenue_cents"]
        touched_profiles[profile["id"]] = profile
        if profile["household_id"] is not None:
            household = db.store["households"].get(profile["household_id"])
            if household is not None:
                touched_households[household["id"]] = household
    for profile in db.by_seq(list(touched_profiles.values())):
        db.touch(profile)
    for household in db.by_seq(list(touched_households.values())):
        derive.refresh_household(household)
        db.touch(household)
    db.touch(activation)
    db.touch(destination)
    return activation


# ------------------------------------------------------- computed reports

def qualifying_conversions(segment):
    anchor = segment["approved_at"]
    if anchor is None:
        return []
    rows = []
    for activation in derive.segment_activations(segment["id"]):
        if activation["status"] == "DRAFT":
            continue
        for index, conversion in enumerate(activation["attributed_conversions"]):
            if conversion["converted_at"] < anchor:
                continue
            rows.append((conversion["converted_at"], activation["created_at"],
                         activation["_seq"], index, conversion))
    rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return [row[4] for row in rows]


def performance(segment, basis):
    conversions = qualifying_conversions(segment)
    member_count = len(derive.segment_members(segment))
    if basis == "INCREMENTAL":
        seen = set()
        credited = []
        for conversion in conversions:
            if conversion["profile_id"] in seen:
                continue
            seen.add(conversion["profile_id"])
            credited.append(conversion)
    else:
        credited = conversions
    revenue = sum(c["revenue_cents"] for c in credited)
    unique = len({c["profile_id"] for c in conversions})
    if member_count == 0:
        per_member = 0
    else:
        per_member = int(calc.round_half_up(
            Decimal(revenue) / Decimal(member_count), 0
        ))
    return {
        "segment_id": segment["id"],
        "attribution_basis": basis,
        "member_count": member_count,
        "conversion_count": len(credited),
        "unique_converter_count": unique,
        "attributed_revenue_cents": revenue,
        "revenue_per_member_cents": per_member,
    }


def _ratio(numerator, denominator):
    if denominator == 0:
        return Decimal("0.0000")
    return calc.round_half_up(Decimal(numerator) / Decimal(denominator), 4)


def overlap(segment, other):
    left = {p["id"] for p in derive.segment_members(segment)}
    right = {p["id"] for p in derive.segment_members(other)}
    shared = left & right
    union = len(left) + len(right) - len(shared)
    return {
        "segment_id": segment["id"],
        "other_segment_id": other["id"],
        "segment_member_count": len(left),
        "other_segment_member_count": len(right),
        "overlap_count": len(shared),
        "union_count": union,
        "jaccard_index": float(_ratio(len(shared), union)),
        "containment_in_other": float(_ratio(len(shared), len(left))),
        "containment_of_other": float(_ratio(len(shared), len(right))),
    }
