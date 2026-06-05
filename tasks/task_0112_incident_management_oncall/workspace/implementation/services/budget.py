"""Error-budget calculations (PRD 3.5).

Two structurally different accountings over the same incident set:
  - time_based consumed  : per-incident ceil(downtime) then sum
  - event_based cost     : fixed per-severity cost, ignores downtime
Plus service_budget_status with inclusive >= boundaries.
"""
import math

from db import db

WARNING_THRESHOLD_PCT = 0.8
EVENT_COST_MINUTES = {"SEV1": 60, "SEV2": 30, "SEV3": 10, "SEV4": 5}


def _resolved_budget_incidents(svc):
    """RESOLVED incidents on this service with counts_against_budget == true."""
    out = []
    for inc in db.incidents.values():
        if inc["service_id"] != svc["id"]:
            continue
        if inc["lifecycle_status"] != "RESOLVED":
            continue
        if not inc["counts_against_budget"]:
            continue
        out.append(inc)
    return out


def incident_downtime_minutes(inc):
    """ceil((resolved_at - triggered_at) / 60s); 0 if not eligible."""
    if inc["lifecycle_status"] != "RESOLVED" or not inc["counts_against_budget"]:
        return 0
    if inc.get("resolved_at") is None:
        return 0
    seconds = (inc["resolved_at"] - inc["triggered_at"]).total_seconds()
    if seconds <= 0:
        return 0
    return math.ceil(seconds / 60.0)


def consumed_minutes(svc):
    """calc error_budget_consumed: round-per-incident-then-sum."""
    total = 0
    for inc in _resolved_budget_incidents(svc):
        total += incident_downtime_minutes(inc)
    return total


def event_cost_minutes(svc):
    """calc error_budget_event_cost: fixed per-severity, summed."""
    total = 0
    for inc in _resolved_budget_incidents(svc):
        total += EVENT_COST_MINUTES[inc["severity"]]
    return total


def budget_status(svc, consumed=None):
    """calc service_budget_status; inclusive >= boundaries."""
    if consumed is None:
        consumed = consumed_minutes(svc)
    budget = svc["error_budget_minutes"]
    if consumed >= budget:
        return "EXHAUSTED"
    warning_threshold = math.ceil(budget * WARNING_THRESHOLD_PCT)
    if consumed >= warning_threshold:
        return "WARNING"
    return "HEALTHY"
