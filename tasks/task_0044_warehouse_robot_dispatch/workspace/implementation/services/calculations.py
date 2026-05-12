"""Pure calculation rules: priority_score, robot_selection, parent_task_status,
charge_progression boundary helpers, metrics computation."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

from db import db, to_unix


PRIORITY_BASE = {"CRITICAL": 0, "HIGH": 1000, "NORMAL": 2000, "LOW": 3000}
AGING_BUCKET_SECONDS = 60
AGING_BUCKET_WEIGHT = 10
MAX_ROLLBACKS = 3
HEARTBEAT_TIMEOUT_SECONDS = 15
DEADLOCK_PENALTY = 1000
BOTTLENECK_TOP_K = 5


def compute_priority_score(task: dict, fleet: dict) -> int:
    base = PRIORITY_BASE.get(task["priority_class"], 2000)
    if task.get("queued_at") is None:
        return base
    age_sec = max(0, to_unix(fleet["clock_now"]) - to_unix(task["queued_at"]))
    discount = (age_sec // AGING_BUCKET_SECONDS) * AGING_BUCKET_WEIGHT
    return base - discount


def round_half_up(value, places: int):
    """Round half-up using Decimal."""
    q = Decimal(10) ** -places
    return float(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


def has_non_terminal_descendants(task: dict) -> bool:
    """True if task has direct children with status not in terminal-equivalent set."""
    children = [t for t in db.tasks.values() if t.get("parent_task_id") == task["id"]]
    if not children:
        return False
    for c in children:
        if c["status"] not in {"CANCELLED", "EXPIRED", "MERGED"}:
            # Any non-terminal child means parent is still gated for dispatch/cancel.
            # For dispatch-exclusion: status NOT IN {CANCELLED, EXPIRED, MERGED}
            return True
    return False


def has_non_terminal_descendants_for_cancel(task: dict) -> bool:
    """For cancellation: descendants must be in {CANCELLED, COMPLETED, EXPIRED, MERGED}."""
    children = [t for t in db.tasks.values() if t.get("parent_task_id") == task["id"]]
    for c in children:
        if c["status"] not in {"CANCELLED", "COMPLETED", "EXPIRED", "MERGED"}:
            return True
    return False
