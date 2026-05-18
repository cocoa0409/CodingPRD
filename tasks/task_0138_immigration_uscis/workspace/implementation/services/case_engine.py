"""Core state-machine engine and audit-event emission for Cases and children.

Centralises:
  * stamping common fields on create / update
  * emitting CaseEvent rows
  * the priority-date refresh helper used by /file, /refresh-priority-date,
    and the I-130 approval cascade
  * the I-130 → dependent I-485 cascades on APPROVE and DENY
  * the clock-advance sweep that auto-expires RFEs and triggers cascade
"""
from __future__ import annotations

from datetime import datetime, timezone

from db import store
from utils import new_uuid

from services.calculations import (
    compute_priority_date_status,
    recompute_with_retrogression,
)


# ────────────────────────────────────────────────────────────────────────────
# Common-field stamping
# ────────────────────────────────────────────────────────────────────────────


def stamp_create(entity: dict, now: datetime) -> dict:
    """Initialise common fields for a brand-new entity (PRD §2.5).

    Adds: id, created_at, updated_at, version. Returns the entity for
    chained writes.
    """
    entity.setdefault("id", new_uuid())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def stamp_update(entity: dict, now: datetime) -> dict:
    """Bump version + refresh updated_at on a mutating write."""
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 1) + 1
    return entity


# ────────────────────────────────────────────────────────────────────────────
# CaseEvent emission
# ────────────────────────────────────────────────────────────────────────────


def emit_case_event(
    case_id: str,
    event_type: str,
    actor_role: str,
    now: datetime,
    from_value=None,
    to_value=None,
):
    event = {
        "id": new_uuid(),
        "created_at": now,
        "case_id": case_id,
        "event_type": event_type,
        "from_value": str(from_value) if from_value is not None else None,
        "to_value": str(to_value) if to_value is not None else None,
        "actor_role": actor_role,
        "occurred_at": now,
    }
    store.case_events[event["id"]] = event
    return event


# ────────────────────────────────────────────────────────────────────────────
# Priority-date refresh (with audit event for explicit refresh)
# ────────────────────────────────────────────────────────────────────────────


def refresh_priority_date_status(case: dict, actor_role: str, now: datetime, *, emit_event: bool = False):
    """Recompute priority_date_status with retrogression detection.

    Mutates `case` in place. When `emit_event` is True (used by the
    /refresh-priority-date endpoint and I-130 cascade hop 2), emits a
    PRIORITY_DATE_RECOMPUTED CaseEvent capturing the prior and new values.
    """
    previous = case.get("priority_date_status", "NOT_APPLICABLE")
    new_status = recompute_with_retrogression(case)
    if new_status != previous:
        case["priority_date_status"] = new_status
        stamp_update(case, now)
        if emit_event:
            emit_case_event(
                case["id"], "PRIORITY_DATE_RECOMPUTED", actor_role, now,
                from_value=previous, to_value=new_status,
            )
    elif emit_event:
        # Even when unchanged, emit so callers can see the recomputation.
        emit_case_event(
            case["id"], "PRIORITY_DATE_RECOMPUTED", actor_role, now,
            from_value=previous, to_value=new_status,
        )
    return case["priority_date_status"]


# ────────────────────────────────────────────────────────────────────────────
# I-130 approval cascade — propagate priority_date onto dependent I-485s
# ────────────────────────────────────────────────────────────────────────────


def cascade_i130_approval(parent_case: dict, actor_role: str, now: datetime):
    """When an I-130 is APPROVED, propagate priority_date and recompute."""
    parent_pd = parent_case.get("priority_date")
    for dep in list(store.cases.values()):
        if dep.get("linked_i130_case_id") != parent_case["id"]:
            continue
        if dep["case_type"] != "I-485":
            continue
        if dep.get("priority_date") is not None:
            continue
        if parent_pd is None:
            continue
        dep["priority_date"] = parent_pd
        stamp_update(dep, now)
        # Hop 2: recompute dependent's priority_date_status.
        refresh_priority_date_status(dep, actor_role, now, emit_event=True)


# ────────────────────────────────────────────────────────────────────────────
# I-130 denial cascade — force dependent I-485s to DENIED, cancel children
# ────────────────────────────────────────────────────────────────────────────


def cascade_i130_denial(parent_case: dict, actor_role: str, now: datetime) -> int:
    """Cascade an I-130 denial onto every dependent I-485.

    Returns the number of dependent I-485s that were forced to DENIED. This
    count is summed into the sweep's auto_denied_cases tally per PRD §3.10:
    "auto_denied_cases (the count of cases auto-denied as a result)".
    """
    terminal = {"APPROVED", "DENIED", "WITHDRAWN"}
    denied_count = 0
    for dep in list(store.cases.values()):
        if dep.get("linked_i130_case_id") != parent_case["id"]:
            continue
        if dep["case_type"] != "I-485":
            continue
        if dep["status"] in terminal:
            continue
        previous_status = dep["status"]
        dep["status"] = "DENIED"
        dep["denial_reason"] = "INELIGIBLE"
        dep["decision_at"] = now
        stamp_update(dep, now)
        emit_case_event(
            dep["id"], "DECISION_RECORDED", actor_role, now,
            from_value=previous_status, to_value="DENIED",
        )
        denied_count += 1
        # Hop 3: cancel SCHEDULED Biometrics and Interviews on the dependent.
        for bio in store.biometrics.values():
            if bio["case_id"] == dep["id"] and bio["status"] == "SCHEDULED":
                bio["status"] = "CANCELLED"
                stamp_update(bio, now)
        for itv in store.interviews.values():
            if itv["case_id"] == dep["id"] and itv["status"] == "SCHEDULED":
                itv["status"] = "CANCELLED"
                stamp_update(itv, now)
    return denied_count


# ────────────────────────────────────────────────────────────────────────────
# Clock advance sweep — auto-expire RFEs, cascade to I-130 denial
# ────────────────────────────────────────────────────────────────────────────


def clock_advance_sweep(now: datetime) -> tuple[int, int]:
    """For every OUTSTANDING RFE whose deadline_at < now(), expire it and
    auto-deny the parent case. Then for any auto-denied I-130, run the
    standard cascade onto dependent I-485s.

    Returns (expired_rfes, auto_denied_cases).
    """
    expired_count = 0
    auto_denied_count = 0
    auto_denied_i130s: list[dict] = []

    # Iterate a snapshot of RFEs since we may mutate.
    for rfe in list(store.rfes.values()):
        if rfe["status"] != "OUTSTANDING":
            continue
        if now <= rfe["deadline_at"]:
            continue
        # Expire this RFE.
        rfe["status"] = "EXPIRED"
        stamp_update(rfe, now)
        expired_count += 1

        case = store.cases.get(rfe["case_id"])
        if case is None:
            continue
        # If already terminal, skip (defensive; under normal flow it can't be).
        if case["status"] in {"APPROVED", "DENIED", "WITHDRAWN"}:
            continue
        previous_status = case["status"]
        case["status"] = "DENIED"
        case["denial_reason"] = "RFE_TIMEOUT"
        case["decision_at"] = now
        case["rfe_deadline"] = None
        stamp_update(case, now)
        emit_case_event(
            case["id"], "DECISION_RECORDED", "system", now,
            from_value=previous_status, to_value="DENIED",
        )
        auto_denied_count += 1
        if case["case_type"] == "I-130":
            auto_denied_i130s.append(case)

    # Cascade onto dependent I-485s (hop 2 + 3) for each auto-denied I-130.
    # PRD §3.10: auto_denied_cases counts every case auto-denied "as a
    # result" of the sweep — including dependents reached by the cascade.
    for i130 in auto_denied_i130s:
        auto_denied_count += cascade_i130_denial(i130, "system", now)

    return expired_count, auto_denied_count
