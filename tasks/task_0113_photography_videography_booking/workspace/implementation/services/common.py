"""Shared entity helpers: common-field stamping, mutation, booking recompute,
and child lookups (PRD §2.4, §2.5, §3.2)."""
from __future__ import annotations

from typing import Any, Dict, List

import db
from services import calculations as calc


# ---- common fields (PRD §2.4) -----------------------------------------------
def stamp_create(entity: Dict[str, Any], with_version: bool = True) -> Dict[str, Any]:
    """Attach id + created_at (+ updated_at + version unless lean)."""
    now = db.now_iso()
    entity["id"] = db.new_uuid()
    entity["created_at"] = now
    entity["_seq"] = db.next_seq()
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity: Dict[str, Any]) -> None:
    """Refresh updated_at and increment version by one on every mutation."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = int(entity.get("version", 0)) + 1


# ---- child lookups ----------------------------------------------------------
def addon_orders_for_booking(booking_id: str) -> List[dict]:
    return [a for a in db.addon_orders.values() if a["booking_id"] == booking_id]


def payments_for_booking(booking_id: str) -> List[dict]:
    return [p for p in db.payments.values() if p["booking_id"] == booking_id]


def schedules_for_booking(booking_id: str) -> List[dict]:
    return [s for s in db.shoot_schedules.values() if s["booking_id"] == booking_id]


def active_schedule_for_booking(booking_id: str):
    """The booking's non-terminal (SCHEDULED/RESCHEDULED) shoot schedule, if any.
    Falls back to most-recently created schedule otherwise."""
    scheds = sorted(schedules_for_booking(booking_id), key=lambda s: s["_seq"])
    non_terminal = [s for s in scheds if s["status"] in ("SCHEDULED", "RESCHEDULED")]
    if non_terminal:
        return non_terminal[-1]
    return scheds[-1] if scheds else None


def assignments_for_schedule(schedule_id: str) -> List[dict]:
    return [a for a in db.second_shooter_assignments.values()
            if a["shoot_schedule_id"] == schedule_id]


def assignments_for_booking(booking_id: str) -> List[dict]:
    sched_ids = {s["id"] for s in schedules_for_booking(booking_id)}
    return [a for a in db.second_shooter_assignments.values()
            if a["shoot_schedule_id"] in sched_ids]


def active_schedule_assignments(booking_id: str) -> List[dict]:
    """Assignments on the booking's active shoot schedule (PRD §3.2)."""
    sched = active_schedule_for_booking(booking_id)
    if sched is None:
        return []
    return assignments_for_schedule(sched["id"])


def contract_for_booking(booking_id: str):
    cands = [c for c in db.contracts.values() if c["booking_id"] == booking_id]
    # at most one non-VOID per booking; prefer the non-VOID one
    non_void = [c for c in cands if c["status"] != "VOID"]
    if non_void:
        return sorted(non_void, key=lambda c: c["_seq"])[-1]
    return sorted(cands, key=lambda c: c["_seq"])[-1] if cands else None


def gallery_for_booking(booking_id: str):
    cands = [gl for gl in db.galleries.values() if gl["booking_id"] == booking_id]
    return sorted(cands, key=lambda gl: gl["_seq"])[-1] if cands else None


# ---- booking recompute (PRD §3.2) -------------------------------------------
def recompute_total_fee(booking: dict) -> None:
    package = db.session_packages[booking["package_id"]]
    addons = addon_orders_for_booking(booking["id"])
    assignments = active_schedule_assignments(booking["id"])
    booking["total_fee_cents"] = calc.booking_total_fee(
        package, booking["requested_shoot_hours"], addons, assignments
    )


def recompute_amount_paid_and_balance(booking: dict) -> None:
    payments = payments_for_booking(booking["id"])
    booking["amount_paid_cents"] = calc.amount_paid(payments)
    booking["balance_due_cents"] = calc.balance_due(
        booking["total_fee_cents"], booking["amount_paid_cents"]
    )
