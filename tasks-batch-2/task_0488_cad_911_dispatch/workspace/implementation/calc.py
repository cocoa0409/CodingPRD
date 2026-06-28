"""Calculation rules (Scaffold Table 3 / PRD §3.3, §3.4, §3.6).

All numeric outputs are exact integers or booleans; no floats, no money.
"""
from datetime import datetime, timezone

from constants import (
    BASE_PRIORITY,
    REQUIRED_DISCIPLINES,
    CAPABILITY_PREFERENCE,
)


def parse_iso(ts):
    """Parse a stored ISO8601 (……Z, 3 fractional digits) to aware datetime."""
    if ts is None:
        return None
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def manhattan(ax, ay, bx, by):
    """Integer Manhattan distance; never rounded (PRD §2.8)."""
    return abs(ax - bx) + abs(ay - by)


def required_disciplines_for(incident_type):
    return list(REQUIRED_DISCIPLINES[incident_type])


def effective_priority_at_intake(incident_type, ali_grid_x, ali_grid_y,
                                 ali_confidence, active_alerts):
    """Four-step fixed-order priority computation (PRD §3.3).

    active_alerts: iterable of PremiseAlert dicts that are active==True.
    Returns (base_priority_level, priority_level, premise_alert_id).
    """
    # Step 1: base from type
    base = BASE_PRIORITY[incident_type]
    priority = base
    premise_alert_id = None

    # Step 2: match active alert at exact grid; lowest min_priority_floor wins,
    # tie-break earliest created_at.
    matched = [
        a for a in active_alerts
        if a.get("active") and a["grid_x"] == ali_grid_x and a["grid_y"] == ali_grid_y
    ]
    if matched:
        matched.sort(key=lambda a: (a["min_priority_floor"], a["created_at"]))
        alert = matched[0]
        premise_alert_id = alert["id"]
        # Step 3: clamp UP in urgency (toward 1)
        priority = min(base, alert["min_priority_floor"])

    # Step 4: applied strictly AFTER premise clamp — UNKNOWN fix is at least 2.
    if ali_confidence == "UNKNOWN":
        priority = min(priority, 2)

    return base, priority, premise_alert_id


def response_time_seconds(first_dispatch_at, first_onscene_at):
    """Dispatch-based response time, floored integer seconds (PRD §3.6)."""
    if not first_dispatch_at or not first_onscene_at:
        return None
    a = parse_iso(first_dispatch_at)
    b = parse_iso(first_onscene_at)
    delta = (b - a).total_seconds()
    return int(delta // 1)


def total_handle_seconds(received_at, first_onscene_at):
    """Call-receipt-based handle time, floored integer seconds (PRD §3.6)."""
    if not received_at or not first_onscene_at:
        return None
    a = parse_iso(received_at)
    b = parse_iso(first_onscene_at)
    delta = (b - a).total_seconds()
    return int(delta // 1)


def governing_sla(incident, assignments, agencies, units):
    """Largest response_sla_seconds among required-discipline agencies that have
    a non-cancelled assignment on this incident; else smallest across agencies
    of the required disciplines (PRD §3.6)."""
    required = set(incident["required_disciplines"])

    # agency ids that have a non-cancelled assignment on this incident
    committed_agency_ids = set()
    for a in assignments:
        if a["incident_id"] != incident["id"]:
            continue
        if a["status"] == "CANCELLED":
            continue
        u = units.get(a["unit_id"])
        if u:
            committed_agency_ids.add(u["agency_id"])

    committed_required_slas = [
        ag["response_sla_seconds"]
        for ag in agencies.values()
        if ag["discipline"] in required and ag["id"] in committed_agency_ids
    ]
    if committed_required_slas:
        return max(committed_required_slas)

    all_required_slas = [
        ag["response_sla_seconds"]
        for ag in agencies.values()
        if ag["discipline"] in required
    ]
    if all_required_slas:
        return min(all_required_slas)
    return None


def sla_breached(handle_seconds, gov_sla):
    """Strict greater-than; equal handle time is NOT a breach (PRD §3.6)."""
    if handle_seconds is None or gov_sla is None:
        return False
    return handle_seconds > gov_sla


def capability_rank(incident_type, capability):
    """0 if capability is among the incident type's preferred tiers, else 1."""
    prefs = CAPABILITY_PREFERENCE.get(incident_type, [])
    return 0 if capability in prefs else 1


def rank_candidates(incident, candidate_units):
    """Sort candidate units by (travel_distance, capability_rank, created_at).

    Returns the sorted list. Tie-break is created_at ASC — never id.
    """
    def key(u):
        dist = manhattan(u["grid_x"], u["grid_y"],
                         incident["ali_grid_x"], incident["ali_grid_y"])
        crank = capability_rank(incident["incident_type"], u["capability"])
        return (dist, crank, u["created_at"])

    return sorted(candidate_units, key=key)


def incident_unit_count(incident_id, assignments):
    """Count ONSCENE/CLEARED assignments rolled into a report (PRD §3.9)."""
    return sum(
        1 for a in assignments
        if a["incident_id"] == incident_id and a["status"] in ("ONSCENE", "CLEARED")
    )
