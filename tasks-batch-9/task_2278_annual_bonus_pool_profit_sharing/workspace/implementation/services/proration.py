"""Participation window, segmentation, proration and pool assignment.

Implements calc `participant_prorated_target` and calc `award_pool_assignment`
(SCAFFOLD.yaml) / PRD 3.3.  The rounding order is pinned: each segment is
rounded to whole cents with ROUND_HALF_UP and the segments are then summed.
"""

from datetime import timedelta
from decimal import Decimal

import db
from errors import ApiError
from services import calc


def _d(value):
    return db.as_date(value)


# ---------------------------------------------------------------------------
# Event views
# ---------------------------------------------------------------------------
def live_transfers(participant_id, plan):
    """Non-superseded TRANSFER events inside [plan_period_start, plan_period_end)."""
    plan_start = _d(plan["plan_period_start"])
    plan_end = _d(plan["plan_period_end"])
    out = []
    for event in db.live_events(participant_id):
        if event["event_type"] != "TRANSFER":
            continue
        effective = _d(event["effective_date"])
        if plan_start <= effective < plan_end:
            out.append(event)
    out.sort(key=lambda e: (e["effective_date"], e["_seq"]))
    return out


def attrs_in_force(participant, transfers, on_date):
    """(job_level, base_salary_cents, business_unit_id) in force on `on_date`.

    The transfer with the latest effective_date at or before `on_date` wins;
    among transfers sharing that date the FIRST recorded one (earliest
    created_at) wins (PRD 3.3).
    """
    candidates = [t for t in transfers if _d(t["effective_date"]) <= on_date]
    if not candidates:
        return (participant["job_level"],
                participant["base_salary_cents"],
                participant["business_unit_id"])
    latest = max(_d(t["effective_date"]) for t in candidates)
    same_day = [t for t in candidates if _d(t["effective_date"]) == latest]
    winner = min(same_day, key=lambda t: t["_seq"])
    return (winner["new_job_level"],
            winner["new_base_salary_cents"],
            winner["new_business_unit_id"])


def participation_window(plan, participant):
    """Half-open [win_start, win_end) participation window."""
    win_start = max(_d(plan["plan_period_start"]), _d(participant["hire_date"]))
    win_end = _d(plan["plan_period_end"])
    if participant["employment_status"] == "TERMINATED" and participant["termination_date"]:
        win_end = min(win_end, _d(participant["termination_date"]) + timedelta(days=1))
    return win_start, win_end


# ---------------------------------------------------------------------------
# Participant derived trio + employment status (PRD 3.2)
# ---------------------------------------------------------------------------
def refresh_participant_derived(plan, participant):
    """Replay non-superseded events (effective_date ASC, created_at ASC)."""
    status = "ACTIVE"
    termination_date = None
    termination_reason = None
    for event in db.live_events(participant["id"]):
        kind = event["event_type"]
        if kind == "LEAVE":
            status = "ON_LEAVE"
        elif kind == "TERMINATION":
            status = "TERMINATED"
            termination_date = event["effective_date"]
            termination_reason = event["termination_reason"]

    participant["employment_status"] = status
    participant["termination_date"] = termination_date
    participant["termination_reason"] = termination_reason

    # The derived trio describes the state in force on the last credited day of
    # the participation window.
    transfers = live_transfers(participant["id"], plan)
    win_start, win_end = participation_window(plan, participant)
    last_credited_day = win_end - timedelta(days=1)
    level, salary, unit = attrs_in_force(participant, transfers, last_credited_day)
    participant["current_job_level"] = level
    participant["current_base_salary_cents"] = salary
    participant["current_business_unit_id"] = unit


# ---------------------------------------------------------------------------
# Proration
# ---------------------------------------------------------------------------
def compute_award_targets(plan, participant, strict=True):
    """Return the award target fields for one participant.

    `strict` raises ERR_JOB_LEVEL_TARGET_MISSING / ERR_POOL_MISSING_FOR_UNIT as
    the target-assignments run requires; cascades run non-strict and degrade
    gracefully instead of rejecting an eligibility event.
    """
    win_start, win_end = participation_window(plan, participant)
    transfers = live_transfers(participant["id"], plan)

    # --- segments ---------------------------------------------------------
    if win_end <= win_start:
        segments = []
    else:
        boundaries = sorted({_d(t["effective_date"]) for t in transfers
                             if win_start < _d(t["effective_date"]) < win_end})
        points = [win_start] + boundaries + [win_end]
        segments = [(points[i], points[i + 1]) for i in range(len(points) - 1)]

    # --- unpaid leave days, chronological, 30-day credit cap ---------------
    unpaid_days = []
    leaves = [e for e in db.live_events(participant["id"])
              if e["event_type"] == "LEAVE" and not e.get("paid_leave")]
    leaves.sort(key=lambda e: (e["effective_date"], e["_seq"]))
    for event in leaves:
        start = _d(event["effective_date"])
        end = _d(event["leave_end_date"])
        if end is None:
            continue
        cursor = start
        while cursor <= end:
            if win_start <= cursor < win_end:
                unpaid_days.append(cursor)
            cursor += timedelta(days=1)
    unpaid_days.sort()
    excluded_days = set(unpaid_days[calc.LEAVE_CREDIT_CAP_DAYS:])
    excluded_leave_days = max(0, len(unpaid_days) - calc.LEAVE_CREDIT_CAP_DAYS)

    # --- per-segment target, rounded per segment then summed ---------------
    prorated_target_cents = 0
    credited_days = 0
    last_pct = Decimal("0.00")
    last_level = participant["current_job_level"]
    for seg_start, seg_end in segments:
        level, salary, _unit = attrs_in_force(participant, transfers, seg_start)
        target_row = db.target_for_level(plan["id"], level)
        if target_row is None:
            if strict:
                raise ApiError("ERR_JOB_LEVEL_TARGET_MISSING",
                               "No job level target for level '%s' in this plan" % level)
            pct = Decimal("0.00")
        else:
            pct = target_row["target_bonus_pct"]
        span = (seg_end - seg_start).days
        excluded_in_segment = sum(1 for day in excluded_days if seg_start <= day < seg_end)
        segment_credited = span - excluded_in_segment
        credited_days += segment_credited
        prorated_target_cents += calc.segment_target_cents(segment_credited, salary, pct)
        last_pct = pct
        last_level = level

    # --- minimum-service gate --------------------------------------------
    if credited_days < calc.MIN_SERVICE_DAYS:
        eligibility_status = "INELIGIBLE_MIN_SERVICE"
        prorated_target_cents = 0
    elif participant["employment_status"] == "TERMINATED":
        eligibility_status = calc.leaver_class(participant["termination_reason"])
    else:
        eligibility_status = "ELIGIBLE"

    # --- pool assignment --------------------------------------------------
    last_credited_day = win_end - timedelta(days=1)
    candidates = [t for t in transfers
                  if t["new_business_unit_id"]
                  and _d(t["effective_date"]) <= last_credited_day]
    if not candidates:
        unit_id = participant["business_unit_id"]
    else:
        latest = max(_d(t["effective_date"]) for t in candidates)
        same_day = [t for t in candidates if _d(t["effective_date"]) == latest]
        unit_id = min(same_day, key=lambda t: t["_seq"])["new_business_unit_id"]

    pool = db.pool_for_unit(plan["id"], unit_id)
    if pool is None and strict:
        raise ApiError("ERR_POOL_MISSING_FOR_UNIT",
                       "No pool exists for business unit '%s' in this plan" % unit_id)

    return {
        "target_bonus_pct": last_pct,
        "credited_days": credited_days,
        "excluded_leave_days": excluded_leave_days,
        "segment_count": len(segments),
        "prorated_target_cents": prorated_target_cents,
        "eligibility_status": eligibility_status,
        "business_unit_id": unit_id,
        "bu_pool_id": pool["id"] if pool else None,
        "_job_level": last_level,
    }
