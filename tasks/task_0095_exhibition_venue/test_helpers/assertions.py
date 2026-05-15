"""Entity assertions and domain invariant checkers.

Each `assert_<entity>` validates the structural envelope of an entity
returned by the API: required fields, types, and PRD-enumerated states.
Domain invariants live alongside.

Per PRD §2.4: Exhibition, Hall, Booth, ExhibitorApplication,
BoothAllocation, DockSlot, WorkOrder, Ticket, and SponsorEntitlement
carry id/created_at/updated_at/version. FloorPlanVersion,
SafetyInspection, and AuditLogEntry are append-only and carry only id
and created_at — they MUST NOT carry updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Lookup helpers (used by tests that fish a specific row out of a list).
# ---------------------------------------------------------------------------
def find_row(rows: List[Dict[str, Any]], **predicates: Any) -> Dict[str, Any]:
    """Return the first row whose fields match every predicate kwarg.

    Raises AssertionError with a helpful summary if no row matches.
    """
    for row in rows:
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    raise AssertionError(
        f"No row matching {predicates}. Saw: "
        f"{[dict((k, r.get(k)) for k in predicates) for r in rows]}"
    )


def select_rows(rows: List[Dict[str, Any]],
                **predicates: Any) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if all(r.get(k) == v for k, v in predicates.items())
    ]


def count_rows(rows: List[Dict[str, Any]], **predicates: Any) -> int:
    return len(select_rows(rows, **predicates))


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    """For entities that carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    version = data.get("version")
    assert isinstance(version, int) and version >= 0, \
        f"version must be a non-negative integer, got {version!r}"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """For append-only entities — id and created_at only.

    Per PRD §2.4 these entities (FloorPlanVersion, SafetyInspection,
    AuditLogEntry) MUST NOT expose updated_at or version.
    """
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Exhibition — PRD §3.1
# ---------------------------------------------------------------------------
_EXHIBITION_STATUSES = {
    "DRAFT", "INTAKE_OPEN", "ALLOCATION_PUBLISHED",
    "SETUP", "OPEN", "TEARDOWN", "CLOSED",
}
_EXHIBITION_POSTURES = {"OPEN", "RESTRICTED", "FROZEN"}


def assert_exhibition(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["theme_code"], str)
    assert is_iso8601_timestamp(data.get("open_date", ""))
    assert is_iso8601_timestamp(data.get("close_date", ""))
    assert isinstance(data["capacity_max"], int)
    assert data["status"] in _EXHIBITION_STATUSES, \
        f"status must be one of {_EXHIBITION_STATUSES}, got {data.get('status')!r}"
    assert data["posture"] in _EXHIBITION_POSTURES, \
        f"posture must be one of {_EXHIBITION_POSTURES}, got {data.get('posture')!r}"
    assert isinstance(data["live_occupancy"], int)
    assert data["live_occupancy"] >= 0
    assert isinstance(data["objection_window_hours"], int)


# ---------------------------------------------------------------------------
# Hall — PRD §3.2
# ---------------------------------------------------------------------------
def assert_hall(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["exhibition_id"], str)
    assert isinstance(data["hall_code"], str)
    assert isinstance(data["zone_label"], str)
    assert isinstance(data["aisle_label"], str)
    assert isinstance(data["grid_rows"], int)
    assert isinstance(data["grid_cols"], int)
    assert isinstance(data["fire_safety_zone_cells"], list)
    assert isinstance(data["floor_plan_active_version"], int)


# ---------------------------------------------------------------------------
# FloorPlanVersion — PRD §3.2, append-only (id + created_at only)
# ---------------------------------------------------------------------------
_FLOOR_PLAN_STATUSES = {"DRAFT", "ACTIVE", "SUPERSEDED"}
_FLOOR_PLAN_CELL_KINDS = {"FIXED", "MODULAR", "FIRE_SAFETY"}


def assert_floor_plan_version(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert isinstance(data["hall_id"], str)
    assert isinstance(data["version_number"], int)
    assert data["version_number"] >= 1
    assert data["status"] in _FLOOR_PLAN_STATUSES, \
        f"status must be one of {_FLOOR_PLAN_STATUSES}, got {data.get('status')!r}"
    assert isinstance(data["cells"], list)
    for cell in data["cells"]:
        assert cell["kind"] in _FLOOR_PLAN_CELL_KINDS


# ---------------------------------------------------------------------------
# Booth — PRD §3.2
# ---------------------------------------------------------------------------
_BOOTH_TIERS = {"STANDARD", "PREMIUM", "ISLAND"}
_BOOTH_STATUSES = {"AVAILABLE", "RESERVED", "ALLOCATED", "RELOCATING", "BLOCKED"}


def assert_booth(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["hall_id"], str)
    assert isinstance(data["floor_plan_version_id"], str)
    assert isinstance(data["code"], str)
    assert isinstance(data["cells"], list) and len(data["cells"]) >= 1
    assert data["tier"] in _BOOTH_TIERS, \
        f"tier must be one of {_BOOTH_TIERS}, got {data.get('tier')!r}"
    assert isinstance(data["is_corner"], bool)
    assert isinstance(data["base_price_cents"], int)
    assert data["base_price_cents"] >= 0
    assert isinstance(data["power_kw_capacity"], (int, float))
    assert isinstance(data["water_lpm_capacity"], (int, float))
    assert isinstance(data["network_mbps_capacity"], int)
    assert data["status"] in _BOOTH_STATUSES


# ---------------------------------------------------------------------------
# ExhibitorApplication — PRD §3.3
# ---------------------------------------------------------------------------
_APPLICATION_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "QUALIFIED",
    "REJECTED", "ALLOCATED", "WITHDRAWN",
}
_TIER_REQUESTS = {"STANDARD", "PREMIUM", "ISLAND"}
_SPONSOR_LEVELS = {"NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM"}


def assert_application(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["exhibition_id"], str)
    assert isinstance(data["exhibitor_id"], str)
    assert isinstance(data["theme_tags"], list)
    assert data["requested_tier"] in _TIER_REQUESTS
    assert data["sponsorship_level"] in _SPONSOR_LEVELS
    assert isinstance(data["seniority_years"], int)
    assert data["status"] in _APPLICATION_STATUSES


# ---------------------------------------------------------------------------
# BoothAllocation — PRD §3.4
# ---------------------------------------------------------------------------
_ALLOCATION_STATUSES = {
    "PROPOSED", "PUBLISHED", "OBJECTED",
    "RELOCATING", "CONFIRMED", "REVOKED",
}


def assert_allocation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["booth_id"], str)
    assert isinstance(data["exhibition_id"], str)
    assert isinstance(data["exhibitor_id"], str)
    assert data["status"] in _ALLOCATION_STATUSES, \
        f"status must be one of {_ALLOCATION_STATUSES}, got {data.get('status')!r}"


# ---------------------------------------------------------------------------
# DockSlot — PRD §3.5
# ---------------------------------------------------------------------------
_DOCK_SLOT_STATUSES = {"OPEN", "BOOKED", "COMPLETED", "CANCELLED"}
_DOCK_SLOT_WINDOWS = {"MOVE_IN", "MOVE_OUT"}


def assert_dock_slot(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["exhibition_id"], str)
    assert isinstance(data["dock_code"], str)
    assert data["window_kind"] in _DOCK_SLOT_WINDOWS, \
        f"window_kind must be one of {_DOCK_SLOT_WINDOWS}, got {data.get('window_kind')!r}"
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in _DOCK_SLOT_STATUSES


# ---------------------------------------------------------------------------
# SafetyInspection — PRD §3.5, append-only (id + created_at only)
# ---------------------------------------------------------------------------
_INSPECTION_KINDS = {"BOOTH_MOVE_IN", "PRE_OPEN", "OVERNIGHT"}
_INSPECTION_RESULTS = {"PASS", "FAIL"}


def assert_safety_inspection(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert isinstance(data["exhibition_id"], str)
    assert data["kind"] in _INSPECTION_KINDS, \
        f"kind must be one of {_INSPECTION_KINDS}, got {data.get('kind')!r}"
    assert data["result"] in _INSPECTION_RESULTS
    assert isinstance(data["inspector_id"], str)


# ---------------------------------------------------------------------------
# WorkOrder — PRD §3.6
# ---------------------------------------------------------------------------
_WORK_ORDER_STATUSES = {
    "DRAFT", "SUBMITTED", "DISPATCHED", "EXECUTED",
    "BILLED", "DISPUTED", "RESOLVED", "CANCELLED",
}
_WORK_ORDER_SERVICE_CODES = {
    "EXTRA_POWER", "FURNITURE", "NETWORK", "CLEANING", "SECURITY",
}


def assert_work_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["exhibition_id"], str)
    assert isinstance(data["allocation_id"], str)
    assert isinstance(data["exhibitor_id"], str)
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert line["service_code"] in _WORK_ORDER_SERVICE_CODES
        assert isinstance(line["quantity"], int)
        assert isinstance(line["unit_price_cents"], int)
    assert data["status"] in _WORK_ORDER_STATUSES


# ---------------------------------------------------------------------------
# Ticket — PRD §3.7
# ---------------------------------------------------------------------------
_TICKET_KINDS = {"VISITOR", "PROFESSIONAL_BUYER", "STUDENT", "VIP"}
_TICKET_CHANNELS = {"ONLINE_PRESALE", "ONSITE"}
_TICKET_STATUSES = {"ISSUED", "SCANNED_IN", "SCANNED_OUT", "VOID", "REFUNDED"}


def assert_ticket(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["exhibition_id"], str)
    assert data["kind"] in _TICKET_KINDS
    assert data["channel"] in _TICKET_CHANNELS
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["qr_code"], str) and len(data["qr_code"]) > 0
    assert data["status"] in _TICKET_STATUSES


# ---------------------------------------------------------------------------
# SponsorEntitlement — PRD §3.8
# ---------------------------------------------------------------------------
_ENTITLEMENT_CODES = {
    "SIGNAGE", "PROGRAM_AD", "LOUNGE", "SPEAKING_SLOT", "BRANDED_GIFT",
}
_SPONSOR_TIERS = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
_ENTITLEMENT_STATUSES = {
    "PLANNED", "IN_PROGRESS", "FULFILLED", "MISSED",
    "MAKE_GOOD_OFFERED", "MAKE_GOOD_ACCEPTED", "WAIVED",
}


def assert_entitlement(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["exhibition_id"], str)
    assert isinstance(data["exhibitor_id"], str)
    assert data["entitlement_code"] in _ENTITLEMENT_CODES
    assert data["sponsor_tier"] in _SPONSOR_TIERS
    assert is_iso8601_timestamp(data.get("deadline", ""))
    assert data["status"] in _ENTITLEMENT_STATUSES, \
        f"status must be one of {_ENTITLEMENT_STATUSES}, got {data.get('status')!r}"


# ---------------------------------------------------------------------------
# AuditLogEntry — PRD §2.11, append-only (id + created_at only)
# ---------------------------------------------------------------------------
_AUDIT_SUBJECT_KINDS = {"ALLOCATION", "ENTITLEMENT"}


def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["subject_kind"] in _AUDIT_SUBJECT_KINDS, \
        f"subject_kind must be one of {_AUDIT_SUBJECT_KINDS}, got {data.get('subject_kind')!r}"
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(before: Dict[str, Any],
                                      after: Dict[str, Any]) -> None:
    """PRD §2.5: a successful mutation increments version by 1 and
    refreshes updated_at.
    """
    before_version = before.get("version")
    after_version = after.get("version")
    assert isinstance(before_version, int) and isinstance(after_version, int)
    assert after_version == before_version + 1, (
        f"version must increment by 1: before={before_version}, "
        f"after={after_version}"
    )
    assert after.get("updated_at") != before.get("updated_at"), (
        "updated_at must be refreshed on mutation"
    )


def assert_iso_timestamp_with_three_millis(value: str) -> None:
    """PRD §2.4 requires three fractional digits on ISO 8601 timestamps.

    The framework's is_iso8601_timestamp accepts the value; this stronger
    helper asserts the millisecond precision explicitly.
    """
    assert is_iso8601_timestamp(value), \
        f"not a valid ISO 8601 timestamp: {value!r}"
    # PRD §2.4 specifies three fractional digits.
    assert "." in value, \
        f"timestamp must carry fractional digits: {value!r}"
    # The portion between '.' and 'Z' must be exactly 3 chars.
    frac = value.rsplit(".", 1)[-1].rstrip("Z")
    assert len(frac) == 3, \
        f"timestamp must carry exactly three fractional digits: {value!r}"


__all__ = [
    "find_row",
    "select_rows",
    "count_rows",
    "assert_exhibition",
    "assert_hall",
    "assert_floor_plan_version",
    "assert_booth",
    "assert_application",
    "assert_allocation",
    "assert_dock_slot",
    "assert_safety_inspection",
    "assert_work_order",
    "assert_ticket",
    "assert_entitlement",
    "assert_audit_log_entry",
    "assert_version_incremented_by_one",
    "assert_iso_timestamp_with_three_millis",
]
