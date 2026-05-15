"""Entity assertions and domain invariants for the Hotel Housekeeping API.

Uses the framework's generic helpers (is_valid_uuid, is_iso8601_timestamp)
under the hood. Each asserter accepts the dict shape returned by the
respective endpoint and verifies all PRD-required fields.
"""
from __future__ import annotations
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'Resources that carry the common fields ... also carry
    created_at and updated_at, both ISO 8601 UTC timestamps with three
    fractional digits, and a version field that is an integer starting
    at 1 on creation and incrementing by 1 on every mutation.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive int, got "
        f"{data.get('version')!r}"
    )


def _assert_common_appendonly(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'Subordinate records — InspectionRecord,
    RoomStatusEvent, LinenMovement as an append-only event, and
    AuditLog — carry only id and created_at; both updated_at and
    version are absent from those entities because they are immutable
    once written.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Room (PRD §3.1, §3.9)
# ---------------------------------------------------------------------------
ROOM_STATUSES = {
    "VACANT_CLEAN", "VACANT_DIRTY", "OCCUPIED_CLEAN", "OCCUPIED_DIRTY",
    "INSPECTED", "OUT_OF_ORDER",
}
ROOM_TYPES = {"STANDARD", "SUITE", "PRESIDENTIAL"}
PMS_OCCUPANCIES = {"VACANT", "OCCUPIED", "DUE_OUT", "NO_SHOW"}


def assert_room(data: dict) -> None:
    """Validate Room envelope (PRD §3.1)."""
    _assert_common_mutable(data, "Room")
    assert isinstance(data.get("room_number"), str)
    assert len(data["room_number"]) > 0
    assert isinstance(data.get("zone_code"), str)
    assert data.get("room_type") in ROOM_TYPES, (
        f"Room.room_type must be in {ROOM_TYPES}, got "
        f"{data.get('room_type')!r}"
    )
    assert isinstance(data.get("vip_flag"), bool)
    assert data.get("pms_occupancy") in PMS_OCCUPANCIES, (
        f"Room.pms_occupancy must be in {PMS_OCCUPANCIES}, got "
        f"{data.get('pms_occupancy')!r}"
    )
    assert data.get("status") in ROOM_STATUSES, (
        f"Room.status must be in {ROOM_STATUSES}, got "
        f"{data.get('status')!r}"
    )
    assert isinstance(data.get("discrepancy_flag"), bool)


# ---------------------------------------------------------------------------
# Housekeeper (PRD §3.6)
# ---------------------------------------------------------------------------
SHIFT_STATUSES = {"OFF_SHIFT", "ON_SHIFT"}


def assert_housekeeper(data: dict) -> None:
    """Validate Housekeeper envelope (PRD §3.6)."""
    _assert_common_mutable(data, "Housekeeper")
    assert isinstance(data.get("employee_code"), str)
    assert len(data["employee_code"]) > 0
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("assigned_zone"), str)
    assert data.get("shift_status") in SHIFT_STATUSES, (
        f"Housekeeper.shift_status must be in {SHIFT_STATUSES}, got "
        f"{data.get('shift_status')!r}"
    )
    assert isinstance(data.get("provisional_workload_minutes"), int)
    assert data["provisional_workload_minutes"] >= 0
    assert isinstance(data.get("realized_workload_minutes"), int)
    assert data["realized_workload_minutes"] >= 0


# ---------------------------------------------------------------------------
# CleaningTask (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------
CLEANING_TASK_STATUSES = {
    "PENDING", "ASSIGNED", "ACCEPTED", "IN_PROGRESS", "SUBMITTED",
    "COMPLETED", "CANCELLED",
}
TASK_SOURCES = {"CHECK_OUT", "STAYOVER", "SCHEDULED"}
PRIORITY_TIERS = {"URGENT", "HIGH", "NORMAL"}


def assert_cleaning_task(data: dict) -> None:
    """Validate CleaningTask envelope (PRD §3.3, §3.5)."""
    _assert_common_mutable(data, "CleaningTask")
    assert is_valid_uuid(data.get("room_id", ""))
    assert data.get("task_source") in TASK_SOURCES, (
        f"CleaningTask.task_source must be in {TASK_SOURCES}, got "
        f"{data.get('task_source')!r}"
    )
    assert isinstance(data.get("expedite_flag"), bool)
    assert isinstance(data.get("priority_score"), int)
    assert data.get("priority_tier") in PRIORITY_TIERS, (
        f"CleaningTask.priority_tier must be in {PRIORITY_TIERS}, got "
        f"{data.get('priority_tier')!r}"
    )
    assert isinstance(data.get("estimated_minutes"), int)
    assert data["estimated_minutes"] >= 0
    assert data.get("status") in CLEANING_TASK_STATUSES, (
        f"CleaningTask.status must be in {CLEANING_TASK_STATUSES}, got "
        f"{data.get('status')!r}"
    )


def assert_priority_tier_for_score(score: int, tier: str) -> None:
    """PRD §3.5: 'a score of at least 100 yields URGENT, a score below
    100 but at least 70 yields HIGH, and a score below 70 yields
    NORMAL.'"""
    if score >= 100:
        expected = "URGENT"
    elif score >= 70:
        expected = "HIGH"
    else:
        expected = "NORMAL"
    assert tier == expected, (
        f"priority_score {score} must produce tier {expected}, got {tier}"
    )


# ---------------------------------------------------------------------------
# MaintenanceTicket (PRD §3.7)
# ---------------------------------------------------------------------------
TICKET_STATUSES = {
    "REPORTED", "DISPATCHED", "IN_REPAIR", "REPAIR_COMPLETED",
    "VERIFIED", "REJECTED",
}
TICKET_CATEGORIES = {
    "ELECTRICAL", "PLUMBING", "HVAC", "FURNITURE", "APPLIANCE", "OTHER",
}
TICKET_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def assert_maintenance_ticket(data: dict) -> None:
    """Validate MaintenanceTicket envelope (PRD §3.7)."""
    _assert_common_mutable(data, "MaintenanceTicket")
    assert is_valid_uuid(data.get("room_id", ""))
    assert is_valid_uuid(data.get("reporter_housekeeper_id", ""))
    assert data.get("category") in TICKET_CATEGORIES
    assert data.get("severity") in TICKET_SEVERITIES
    assert isinstance(data.get("description"), str)
    assert isinstance(data.get("isolates_room"), bool)
    # PRD §3.7: "isolates_room as true exactly when severity is one of
    # HIGH or CRITICAL"
    expected_isolates = data["severity"] in {"HIGH", "CRITICAL"}
    assert data["isolates_room"] == expected_isolates, (
        f"isolates_room must be {expected_isolates} for severity "
        f"{data['severity']}, got {data['isolates_room']}"
    )
    assert data.get("status") in TICKET_STATUSES


# ---------------------------------------------------------------------------
# MinibarItem (PRD §3.11)
# ---------------------------------------------------------------------------
MINIBAR_ITEM_STATUSES = {"ACTIVE", "ARCHIVED"}


def assert_minibar_item(data: dict) -> None:
    """Validate MinibarItem envelope (PRD §3.11)."""
    _assert_common_mutable(data, "MinibarItem")
    assert isinstance(data.get("sku_code"), str)
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("unit_price_cents"), int)
    assert data["unit_price_cents"] >= 0
    assert isinstance(data.get("par_level"), int)
    assert isinstance(data.get("replenishment_threshold"), int)
    assert data.get("status") in MINIBAR_ITEM_STATUSES


# ---------------------------------------------------------------------------
# MinibarConsumption (PRD §3.11)
# ---------------------------------------------------------------------------
MINIBAR_CONSUMPTION_STATUSES = {
    "PENDING", "POSTED", "DISPUTED", "INVESTIGATED", "RESOLVED", "WAIVED",
}
MINIBAR_SOURCE_TYPES = {"HOUSEKEEPER", "GUEST_SELF_REPORT"}


def assert_minibar_consumption(data: dict) -> None:
    """Validate MinibarConsumption envelope (PRD §3.11)."""
    _assert_common_mutable(data, "MinibarConsumption")
    assert is_valid_uuid(data.get("room_id", ""))
    assert data.get("source_type") in MINIBAR_SOURCE_TYPES
    assert isinstance(data.get("line_items"), list)
    assert data.get("status") in MINIBAR_CONSUMPTION_STATUSES


def assert_minibar_charge_integrity(data: dict) -> None:
    """PRD §3.11: 'posted_amount_cents as the gross amount plus the tax'
    — verifies posted_amount_cents == gross_amount_cents + tax_cents.

    PRD §2.8: 'Once a minibar consumption advances past PENDING, its
    gross_amount_cents, tax_cents, and posted_amount_cents are
    immutable, so the folio always reconciles exactly to the moment of
    posting.'
    """
    assert isinstance(data.get("gross_amount_cents"), int)
    assert isinstance(data.get("tax_cents"), int)
    assert isinstance(data.get("posted_amount_cents"), int)
    assert (
        data["posted_amount_cents"]
        == data["gross_amount_cents"] + data["tax_cents"]
    ), (
        "posted_amount_cents must equal gross_amount_cents + tax_cents, "
        f"got {data['posted_amount_cents']} vs "
        f"{data['gross_amount_cents']} + {data['tax_cents']}"
    )


# ---------------------------------------------------------------------------
# LinenType (PRD §3.12)
# ---------------------------------------------------------------------------
LINEN_REPLACEMENT_POLICIES = {"PER_STAY", "SCHEDULED", "ON_REQUEST"}


def assert_linen_type(data: dict) -> None:
    """Validate LinenType envelope (PRD §3.12)."""
    _assert_common_mutable(data, "LinenType")
    assert isinstance(data.get("code"), str)
    assert isinstance(data.get("display_name"), str)
    assert data.get("replacement_policy") in LINEN_REPLACEMENT_POLICIES
    assert isinstance(data.get("par_per_room"), int)
    assert isinstance(data.get("replacement_cost_cents"), int)


# ---------------------------------------------------------------------------
# LinenMovement (append-only — PRD §2.4, §3.12)
# ---------------------------------------------------------------------------
LINEN_MOVEMENT_STATUSES = {
    "COLLECTED", "SENT_TO_LAUNDRY", "RETURNED", "LOSS_REPORTED", "RESOLVED",
}


def assert_linen_movement(data: dict) -> None:
    """Validate LinenMovement envelope (PRD §3.12).

    PRD §2.4: 'LinenMovement is append-only — it carries only id and
    created_at as immutable common metadata.'
    """
    _assert_common_appendonly(data, "LinenMovement")
    assert is_valid_uuid(data.get("room_id", ""))
    assert is_valid_uuid(data.get("linen_type_id", ""))
    assert isinstance(data.get("collected_quantity"), int)
    assert data["collected_quantity"] >= 0
    assert data.get("status") in LINEN_MOVEMENT_STATUSES


def assert_linen_conservation_invariant(movement: dict) -> None:
    """PRD §3.12: 'returned_quantity plus loss_quantity plus
    damage_quantity equals sent_to_laundry_quantity' — must hold once
    the laundry-return event lands.
    """
    sent = movement.get("sent_to_laundry_quantity", 0)
    returned = movement.get("returned_quantity", 0)
    loss = movement.get("loss_quantity", 0)
    damage = movement.get("damage_quantity", 0)
    assert returned + loss + damage == sent, (
        f"Conservation: returned ({returned}) + loss ({loss}) + "
        f"damage ({damage}) must equal sent_to_laundry ({sent})"
    )


# ---------------------------------------------------------------------------
# InspectionRecord (append-only — PRD §2.4, §3.8)
# ---------------------------------------------------------------------------
INSPECTION_OUTCOMES = {"PASS", "FAIL"}


def assert_inspection_record(data: dict) -> None:
    """Validate InspectionRecord envelope (PRD §3.8).

    PRD §2.4 names InspectionRecord as append-only: only id and
    created_at as common metadata.
    """
    _assert_common_appendonly(data, "InspectionRecord")
    assert is_valid_uuid(data.get("cleaning_task_id", ""))
    assert is_valid_uuid(data.get("room_id", ""))
    assert isinstance(data.get("supervisor_id"), str)
    assert isinstance(data.get("sampled_flag"), bool)
    assert isinstance(data.get("checklist_items"), list)
    assert len(data["checklist_items"]) > 0
    assert data.get("outcome") in INSPECTION_OUTCOMES


# ---------------------------------------------------------------------------
# RoomStatusEvent (append-only)
# ---------------------------------------------------------------------------
CHANGE_REASONS = {
    "PMS_SYNC", "TASK_COMPLETED", "INSPECTION_PASS",
    "MAINTENANCE_ISOLATE", "MAINTENANCE_VERIFY", "MANUAL_CORRECTION",
    "INITIAL",
}


def assert_room_status_event(data: dict) -> None:
    """Validate RoomStatusEvent envelope (PRD §2.7, §3.9)."""
    _assert_common_appendonly(data, "RoomStatusEvent")
    assert is_valid_uuid(data.get("room_id", ""))
    assert data.get("change_reason") in CHANGE_REASONS, (
        f"change_reason must be in {CHANGE_REASONS}, got "
        f"{data.get('change_reason')!r}"
    )
    # PRD §2.7: "previous_status (null only for the room's
    # initial-creation event)"
    if data["change_reason"] == "INITIAL":
        assert data.get("previous_status") is None
    else:
        assert data.get("previous_status") in (
            {"VACANT_CLEAN", "VACANT_DIRTY", "OCCUPIED_CLEAN",
             "OCCUPIED_DIRTY", "INSPECTED", "OUT_OF_ORDER"}
        ), f"previous_status invalid: {data.get('previous_status')!r}"
    assert data.get("new_status") in (
        {"VACANT_CLEAN", "VACANT_DIRTY", "OCCUPIED_CLEAN",
         "OCCUPIED_DIRTY", "INSPECTED", "OUT_OF_ORDER"}
    )
    # PRD §2.7: "correction_note that is required exactly when
    # change_reason is MANUAL_CORRECTION and is null otherwise"
    if data["change_reason"] == "MANUAL_CORRECTION":
        assert isinstance(data.get("correction_note"), str)
        assert len(data["correction_note"]) > 0
    else:
        assert data.get("correction_note") is None


# ---------------------------------------------------------------------------
# AuditLog (append-only)
# ---------------------------------------------------------------------------
AUDIT_ACTION_TYPES = {
    "ROOM_STATUS_CHANGE", "MINIBAR_CONSUMPTION_POST",
    "MINIBAR_CONSUMPTION_DISPUTE", "MINIBAR_CONSUMPTION_WAIVE",
    "MANUAL_CORRECTION", "EVENT_INGESTED",
}


def assert_audit_log_entry(data: dict) -> None:
    """Validate AuditLog envelope (PRD §2.7)."""
    _assert_common_appendonly(data, "AuditLog")
    assert isinstance(data.get("actor_id"), str)
    assert data.get("action_type") in AUDIT_ACTION_TYPES, (
        f"action_type must be in {AUDIT_ACTION_TYPES}, got "
        f"{data.get('action_type')!r}"
    )
    assert isinstance(data.get("subject_entity"), str)
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("detail"), dict)


# ---------------------------------------------------------------------------
# Discrepancy invariant (PRD §2.10)
# ---------------------------------------------------------------------------
def assert_room_discrepancy_invariant(data: dict) -> None:
    """PRD §2.10: 'a room whose pms_occupancy is OCCUPIED or DUE_OUT
    while its status is none of OCCUPIED_CLEAN, OCCUPIED_DIRTY, or
    INSPECTED is flagged, and conversely a room whose pms_occupancy is
    VACANT or NO_SHOW while its status is one of the three occupied-side
    statuses is also flagged; in every other combination the flag is
    false.'
    """
    pms_says_occupied = data["pms_occupancy"] in {"OCCUPIED", "DUE_OUT"}
    hk_says_occupied = data["status"] in {
        "OCCUPIED_CLEAN", "OCCUPIED_DIRTY", "INSPECTED",
    }
    expected = pms_says_occupied != hk_says_occupied
    assert data["discrepancy_flag"] == expected, (
        f"discrepancy_flag: pms_occupancy={data['pms_occupancy']}, "
        f"status={data['status']}, expected {expected}, got "
        f"{data['discrepancy_flag']}"
    )


__all__ = [
    "assert_room",
    "assert_room_discrepancy_invariant",
    "assert_housekeeper",
    "assert_cleaning_task",
    "assert_priority_tier_for_score",
    "assert_maintenance_ticket",
    "assert_minibar_item",
    "assert_minibar_consumption",
    "assert_minibar_charge_integrity",
    "assert_linen_type",
    "assert_linen_movement",
    "assert_linen_conservation_invariant",
    "assert_inspection_record",
    "assert_room_status_event",
    "assert_audit_log_entry",
]
