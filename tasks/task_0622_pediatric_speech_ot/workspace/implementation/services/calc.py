"""Calculation rules (scaffold §1.3, PRD §2.6-2.8, §3.2)."""

from decimal import Decimal, ROUND_HALF_UP

from db import db
from clock import parse_iso, week_of, whole_minutes_between


# --------------------------------------------------------------------------
# recommended_weekly_minutes (scaffold §1.3; PRD §3.2)
# --------------------------------------------------------------------------
def recommended_weekly_minutes(severity_score):
    # Single banded recommendation (NOT marginal).
    #   [0,29] -> 30 ; [30,59] -> 60 ; [60,79] -> 90 ; [80,100] -> 120
    if severity_score <= 29:
        return 30
    if severity_score <= 59:
        return 60
    if severity_score <= 79:
        return 90
    return 120


# --------------------------------------------------------------------------
# visit_balance (scaffold §1.3; PRD §2.6)
# --------------------------------------------------------------------------
def visit_counts(auth_id):
    """Return (reserved, committed) for an authorization id from appointments."""
    reserved = 0
    committed = 0
    for appt in db.appointments.values():
        if appt["authorization_id"] != auth_id:
            continue
        if appt["status"] == "SCHEDULED":
            reserved += 1
        elif appt["status"] == "COMPLETED":
            committed += 1
        # CANCELLED and NO_SHOW draw nothing.
    return reserved, committed


def recompute_authorization_counts(auth):
    """Recompute reserved/committed/available on the authorization record (in place)."""
    reserved, committed = visit_counts(auth["id"])
    auth["reserved_visits"] = reserved
    auth["committed_visits"] = committed
    auth["available_visits"] = auth["authorized_visits"] - reserved - committed


# --------------------------------------------------------------------------
# weekly_minutes_load (scaffold §1.3; PRD §2.7)
# --------------------------------------------------------------------------
def scheduled_minutes(therapist_id, week_start, exclude_appt_id=None):
    """Sum of SCHEDULED appointment duration_minutes for a therapist in a given ISO week."""
    total = 0
    for appt in db.appointments.values():
        if appt["id"] == exclude_appt_id:
            continue
        if appt["therapist_id"] != therapist_id:
            continue
        if appt["status"] != "SCHEDULED":
            continue
        if week_of(parse_iso(appt["start_time"])) == week_start:
            total += appt["duration_minutes"]
    return total


# --------------------------------------------------------------------------
# goal_progress (scaffold §1.3; PRD §2.8)
# --------------------------------------------------------------------------
def goal_latest_progress(goal):
    """Chronological latest_progress_pct: recorded_pct of the entry with the
    maximum recorded_session_time; ties broken by created_at ASC (latest-created
    wins). No entries -> baseline_pct.
    """
    entries = [
        e for e in db.goal_progress_entries.values() if e["goal_id"] == goal["id"]
    ]
    if not entries:
        return goal["baseline_pct"]

    def key(e):
        return (parse_iso(e["recorded_session_time"]), e["created_at"])

    winner = max(entries, key=key)
    return winner["recorded_pct"]


def gain_ratio(goal):
    """clamp((latest - baseline) / (target - baseline), 0, 1) as a Decimal."""
    baseline = Decimal(goal["baseline_pct"])
    target = Decimal(goal["target_pct"])
    latest = Decimal(goal["latest_progress_pct"])
    denom = target - baseline
    if denom <= 0:
        # target_pct must exceed baseline_pct by validation; guard anyway.
        return Decimal(1) if latest >= target else Decimal(0)
    ratio = (latest - baseline) / denom
    if ratio < 0:
        ratio = Decimal(0)
    elif ratio > 1:
        ratio = Decimal(1)
    return ratio


def overall_progress_pct(plan_id):
    """Forward-looking weighted roll-up across OPEN+MET goals (PRD §2.8)."""
    goals = [
        g
        for g in db.goals.values()
        if g["plan_of_care_id"] == plan_id and g["status"] in ("OPEN", "MET")
    ]
    weight_sum = Decimal(0)
    weighted = Decimal(0)
    for g in goals:
        w = Decimal(g["weight"])
        weight_sum += w
        weighted += w * gain_ratio(g)
    if weight_sum == 0:
        return 0.0
    value = (Decimal(100) * weighted / weight_sum).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(value)
