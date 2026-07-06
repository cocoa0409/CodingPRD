"""SLA due computation + state evaluation (calc sla_due, PRD §3.4).

Boundary is STRICT '>': clock exactly == due is ON_TRACK; due+1s is breached.
Resolution breach dominates response breach when both windows elapsed.
"""
from clock import parse_iso, add_minutes, add_hours, iso
from db import db


def sla_policy_for(priority):
    for p in db.sla_policies.values():
        if p["tier"] == priority:
            return p
    return None


def compute_due(assigned_at_iso, priority):
    """Return (response_due_iso, resolution_due_iso) or (None, None)."""
    policy = sla_policy_for(priority)
    if assigned_at_iso is None or policy is None:
        return None, None
    base = parse_iso(assigned_at_iso)
    response_due = add_minutes(base, policy["response_minutes"])
    resolution_due = add_hours(base, policy["resolution_hours"])
    return iso(response_due), iso(resolution_due)


def sla_state(task):
    """Evaluate sla_state against the current logical clock (calc sla_due).

    Priority order, strict '>':
      DONE      -> latched RESOLUTION_BREACHED if completed_at > resolution_due
      else clock > resolution_due       -> RESOLUTION_BREACHED
      else first_action null & clock > response_due -> RESPONSE_BREACHED
      else                               -> ON_TRACK
    """
    response_due = task.get("response_due_iso")
    resolution_due = task.get("resolution_due_iso")
    if task["status"] == "ASSIGNED" or resolution_due is None:
        # Before assignment there are no due dates; default ON_TRACK.
        if resolution_due is None:
            return "ON_TRACK"

    now = db.clock.get()

    if task["status"] == "DONE":
        completed = task.get("completed_at_iso")
        if completed is not None and resolution_due is not None:
            if parse_iso(completed) > parse_iso(resolution_due):
                return "RESOLUTION_BREACHED"
        return "ON_TRACK"

    if resolution_due is not None and now > parse_iso(resolution_due):
        return "RESOLUTION_BREACHED"

    if task.get("first_action_at_iso") is None and response_due is not None:
        if now > parse_iso(response_due):
            return "RESPONSE_BREACHED"

    return "ON_TRACK"
