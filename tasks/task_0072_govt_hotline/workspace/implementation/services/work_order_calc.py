"""Calculations on WorkOrder: difficulty_score, priority_flag, warning_state, opinion aggregation."""

from datetime import timedelta
import math

import clock
import db
from business_hours import business_hours_between

URGENCY_WEIGHT = {"LOW": 0, "NORMAL": 1, "HIGH": 3, "CRITICAL": 5}


def difficulty_score(urgency: str, category_difficulty: int, joint_handling: bool) -> int:
    """Composite difficulty score (calculations.work_order_difficulty_score)."""
    raw = URGENCY_WEIGHT.get(urgency, 0) + int(category_difficulty or 1) + (2 if joint_handling else 0)
    clamped = max(1, min(10, raw))
    # round_half_up step (no-op on integers; preserved for symmetry).
    return int(clamped)


def priority_flag(urgency: str, score: int) -> bool:
    return URGENCY_WEIGHT.get(urgency, 0) >= URGENCY_WEIGHT["HIGH"] or int(score) >= 7


def compute_warning_state(work_order: dict) -> str:
    """Recompute warning_state from current clock per calculations.warning_state."""
    stat = work_order.get("statutory_deadline_at")
    com = work_order.get("committed_deadline_at")
    if not stat or not com:
        return "NONE"
    now_dt = clock.now()
    stat_dt = clock.parse_iso(stat)
    com_dt = clock.parse_iso(com)
    reg_dt = clock.parse_iso(work_order["registered_at"])

    # BREACHED requires strict > past statutory deadline.
    if now_dt > stat_dt:
        return "BREACHED"

    total = (com_dt - reg_dt).total_seconds()
    remaining = (com_dt - now_dt).total_seconds()
    pct = (remaining / total) if total > 0 else 0.0

    if pct <= 0:
        return "RED"
    if pct <= 0.25:
        return "YELLOW"
    return "NONE"


def supporting_assignments_for(work_order_id: str) -> list[dict]:
    return [
        a for a in db.all_rows("department_assignments")
        if a["work_order_id"] == work_order_id and a["role"] == "SUPPORTING"
    ]


def opinion_aggregation(work_order: dict) -> str:
    """Return AGREE | PENDING | DISAGREE_BLOCKING | DISAGREE_OUTVOTED."""
    if not work_order.get("joint_handling"):
        return "AGREE"
    supporting = supporting_assignments_for(work_order["id"])
    if not supporting:
        return "AGREE"
    submitted = [a for a in supporting if a["stage_status"] == "OPINION_SUBMITTED"]
    if len(submitted) < len(supporting):
        return "PENDING"
    N = len(submitted)
    D = sum(1 for a in submitted if a.get("opinion_decision") == "DISAGREE")
    if D == 0:
        return "AGREE"
    if D >= math.ceil(N / 2):
        return "DISAGREE_BLOCKING"
    return "DISAGREE_OUTVOTED"
