"""Workload computations for housekeepers."""

from db import DB
from services.time_util import start_of_today_utc, parse_iso


def compute_provisional_workload(housekeeper_id: str) -> int:
    total = 0
    for t in DB["cleaning_tasks"].values():
        if t.get("assigned_housekeeper_id") != housekeeper_id:
            continue
        if t["status"] in {"ASSIGNED", "ACCEPTED", "IN_PROGRESS", "SUBMITTED"}:
            est = t.get("estimated_minutes") or 0
            total += int(est)
    return total


def compute_realized_workload(housekeeper_id: str) -> int:
    total = 0
    start = start_of_today_utc()
    for t in DB["cleaning_tasks"].values():
        if t.get("assigned_housekeeper_id") != housekeeper_id:
            continue
        if t["status"] != "COMPLETED":
            continue
        sub_at = parse_iso(t.get("submitted_at"))
        if sub_at is None or sub_at < start:
            continue
        actual = t.get("actual_minutes") or 0
        total += int(actual)
    return total
