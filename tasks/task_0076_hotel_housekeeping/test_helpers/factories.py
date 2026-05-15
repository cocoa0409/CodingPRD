"""Payload factories — one per endpoint that takes a body.

Only fields from PRD §3 / §4 input columns. Each factory accepts
**overrides so individual tests can vary specific values without
re-typing the whole payload.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def _short() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Room (PRD §3.1)
# ---------------------------------------------------------------------------
def create_room_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 input set: room_number, zone_code, room_type, vip_flag?,
    pms_occupancy?.

    'A front-desk agent creates a Room by supplying its room_number, a
    zone_code indicating the housekeeping zone ..., and a room_type
    drawn from STANDARD, SUITE, or PRESIDENTIAL; vip_flag and
    pms_occupancy are optional on creation.'
    """
    defaults: Dict[str, Any] = {
        "room_number": f"R-{_short()}",
        "zone_code": TEST_DEFAULTS["ZONE_DEFAULT"],
        "room_type": TEST_DEFAULTS["ROOM_TYPE_STANDARD"],
    }
    defaults.update(overrides)
    return defaults


def correct_room_status_payload(
    new_status: str,
    correction_note: str = "supervisor manual correction",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.10: 'A supervisor may correct a room's status by posting
    a new_status together with a required correction_note and an
    optional version for optimistic concurrency.'"""
    payload: Dict[str, Any] = {
        "new_status": new_status,
        "correction_note": correction_note,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Housekeeper (PRD §3.6)
# ---------------------------------------------------------------------------
def create_housekeeper_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'A supervisor creates a Housekeeper by supplying
    employee_code, display_name, and assigned_zone.'"""
    defaults: Dict[str, Any] = {
        "employee_code": f"EC-{_short()}",
        "display_name": f"Housekeeper {_short()}",
        "assigned_zone": TEST_DEFAULTS["ZONE_DEFAULT"],
    }
    defaults.update(overrides)
    return defaults


def toggle_shift_payload(shift_status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"shift_status": shift_status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CleaningTask (PRD §3.3)
# ---------------------------------------------------------------------------
def create_cleaning_task_payload(
    room_id: str,
    task_source: str = "SCHEDULED",
    expedite_flag: Optional[bool] = None,
    early_check_in_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'A manual creation supplies room_id, the task_source,
    and optionally expedite_flag and early_check_in_at.'"""
    payload: Dict[str, Any] = {
        "room_id": room_id,
        "task_source": task_source,
    }
    if expedite_flag is not None:
        payload["expedite_flag"] = expedite_flag
    if early_check_in_at is not None:
        payload["early_check_in_at"] = early_check_in_at
    payload.update(overrides)
    return payload


def patch_cleaning_task_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'A supervisor may also edit a pending or in-flight task
    to change its task_source, expedite_flag, or early_check_in_at,
    optionally passing version to lock the update.'"""
    return dict(overrides)


def reassign_cleaning_task_payload(
    new_housekeeper_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'A supervisor may reassign an ASSIGNED or ACCEPTED
    task by supplying a new_housekeeper_id in the body.'"""
    payload = {"new_housekeeper_id": new_housekeeper_id}
    payload.update(overrides)
    return payload


def inspect_cleaning_task_payload(
    outcome: str,
    checklist_items: Optional[List[Dict[str, Any]]] = None,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'A supervisor inspects a submitted cleaning task by
    posting an inspection containing the outcome (PASS or FAIL), a
    non-empty checklist_items array, and optional notes.'"""
    if checklist_items is None:
        # Default: produce a checklist that matches the outcome so
        # validation doesn't trip ERR_INVALID_INSPECTION_CHECKLIST.
        if outcome == "PASS":
            checklist_items = [
                {"item_code": "BATHROOM", "passed": True},
                {"item_code": "BED", "passed": True},
                {"item_code": "FLOOR", "passed": True},
            ]
        else:
            checklist_items = [
                {"item_code": "BATHROOM", "passed": False,
                 "note": "stains visible"},
                {"item_code": "BED", "passed": True},
            ]
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "checklist_items": checklist_items,
    }
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MaintenanceTicket (PRD §3.7)
# ---------------------------------------------------------------------------
def create_maintenance_ticket_payload(
    room_id: str,
    reporter_housekeeper_id: str,
    category: str = "PLUMBING",
    severity: str = "MEDIUM",
    description: str = "issue reported by housekeeper",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'Any housekeeper or supervisor reports a maintenance
    issue by creating a MaintenanceTicket against a room, supplying
    room_id, reporter_housekeeper_id, a category drawn from ..., a
    severity drawn from ..., and a free-text description.'"""
    payload: Dict[str, Any] = {
        "room_id": room_id,
        "reporter_housekeeper_id": reporter_housekeeper_id,
        "category": category,
        "severity": severity,
        "description": description,
    }
    payload.update(overrides)
    return payload


def dispatch_maintenance_ticket_payload(
    engineering_assignee: str = "eng-default",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'A supervisor dispatches a reported ticket by
    supplying an engineering_assignee opaque identifier.'"""
    payload = {"engineering_assignee": engineering_assignee}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Minibar (PRD §3.11)
# ---------------------------------------------------------------------------
def create_minibar_item_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.11: 'A supervisor creates a MinibarItem by supplying
    sku_code (unique across active items), display_name,
    unit_price_cents, par_level, and replenishment_threshold.'"""
    defaults: Dict[str, Any] = {
        "sku_code": f"SKU-{_short()}",
        "display_name": f"Item {_short()}",
        "unit_price_cents": TEST_DEFAULTS["MINIBAR_UNIT_PRICE_CENTS"],
        "par_level": TEST_DEFAULTS["MINIBAR_PAR_LEVEL"],
        "replenishment_threshold": TEST_DEFAULTS["MINIBAR_REPLENISH_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_minibar_consumption_payload(
    room_id: str,
    source_type: str,
    line_items: List[Dict[str, Any]],
    cleaning_task_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.11: 'the payload carries room_id, a source_type of either
    HOUSEKEEPER or GUEST_SELF_REPORT, a line_items array, and an
    optional cleaning_task_id linking to the originating cleaning task
    (which must be null exactly when source_type is GUEST_SELF_REPORT).'
    """
    payload: Dict[str, Any] = {
        "room_id": room_id,
        "source_type": source_type,
        "line_items": line_items,
    }
    if cleaning_task_id is not None:
        payload["cleaning_task_id"] = cleaning_task_id
    payload.update(overrides)
    return payload


def dispute_minibar_payload(
    dispute_note: str = "guest claims not consumed",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"dispute_note": dispute_note}
    payload.update(overrides)
    return payload


def investigate_minibar_payload(
    finding_note: str = "supervisor investigation note",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"finding_note": finding_note}
    payload.update(overrides)
    return payload


def resolve_minibar_payload(keep_charge: bool, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"keep_charge": keep_charge}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Linen (PRD §3.12)
# ---------------------------------------------------------------------------
def create_linen_type_payload(
    replacement_policy: str = "PER_STAY",
    scheduled_interval_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.12: 'A supervisor creates a LinenType by supplying code
    (unique across active linen types), display_name, a
    replacement_policy drawn from PER_STAY, SCHEDULED, or ON_REQUEST,
    an optional scheduled_interval_days (required when
    replacement_policy is SCHEDULED, omitted otherwise), par_per_room,
    and replacement_cost_cents.'"""
    payload: Dict[str, Any] = {
        "code": f"LC-{_short()}",
        "display_name": f"Linen {_short()}",
        "replacement_policy": replacement_policy,
        "par_per_room": TEST_DEFAULTS["LINEN_PAR_PER_ROOM"],
        "replacement_cost_cents": TEST_DEFAULTS["LINEN_REPLACEMENT_COST_CENTS"],
    }
    if replacement_policy == "SCHEDULED":
        payload["scheduled_interval_days"] = (
            scheduled_interval_days
            if scheduled_interval_days is not None
            else TEST_DEFAULTS["LINEN_SCHEDULED_INTERVAL_DAYS"]
        )
    payload.update(overrides)
    return payload


def create_linen_movement_payload(
    room_id: str,
    linen_type_id: str,
    collected_quantity: int = 1,
    cleaning_task_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.12: 'A housekeeper records the actual collection by
    creating a LinenMovement with room_id, linen_type_id, optional
    cleaning_task_id, and collected_quantity (must be zero or
    greater).'"""
    payload: Dict[str, Any] = {
        "room_id": room_id,
        "linen_type_id": linen_type_id,
        "collected_quantity": collected_quantity,
    }
    if cleaning_task_id is not None:
        payload["cleaning_task_id"] = cleaning_task_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inbound events / test clock (PRD §3.2, §3.7, §3.12, §2.11)
# ---------------------------------------------------------------------------
def pms_sync_payload(
    room_number: str,
    event_type: str,
    pms_occupancy: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'addressing each event by room_number and supplying an
    event_type and a target pms_occupancy.'"""
    payload: Dict[str, Any] = {
        "room_number": room_number,
        "event_type": event_type,
        "pms_occupancy": pms_occupancy,
    }
    payload.update(overrides)
    return payload


def engineering_update_payload(
    ticket_id: str,
    new_status: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'an engineering-update event carrying ticket_id and
    new_status.'"""
    payload = {"ticket_id": ticket_id, "new_status": new_status}
    payload.update(overrides)
    return payload


def laundry_return_payload(
    movement_id: str,
    returned_quantity: int,
    loss_quantity: int,
    damage_quantity: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.12: 'The laundry-return inbound event carries movement_id,
    returned_quantity, loss_quantity, and damage_quantity.'"""
    payload = {
        "movement_id": movement_id,
        "returned_quantity": returned_quantity,
        "loss_quantity": loss_quantity,
        "damage_quantity": damage_quantity,
    }
    payload.update(overrides)
    return payload


def clock_advance_payload(minutes: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.11: 'A test-driving capability advances the logical clock
    by a supplied number of minutes.'"""
    payload: Dict[str, Any] = {"minutes": minutes}
    payload.update(overrides)
    return payload


__all__ = [
    "create_room_payload",
    "correct_room_status_payload",
    "create_housekeeper_payload",
    "toggle_shift_payload",
    "create_cleaning_task_payload",
    "patch_cleaning_task_payload",
    "reassign_cleaning_task_payload",
    "inspect_cleaning_task_payload",
    "create_maintenance_ticket_payload",
    "dispatch_maintenance_ticket_payload",
    "create_minibar_item_payload",
    "create_minibar_consumption_payload",
    "dispute_minibar_payload",
    "investigate_minibar_payload",
    "resolve_minibar_payload",
    "create_linen_type_payload",
    "create_linen_movement_payload",
    "pms_sync_payload",
    "engineering_update_payload",
    "laundry_return_payload",
    "clock_advance_payload",
]
