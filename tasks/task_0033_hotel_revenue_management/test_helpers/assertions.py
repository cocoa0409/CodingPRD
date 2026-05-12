"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks are pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares; computed-field
presence is asserted only when the PRD explicitly states the field is
exposed on the listed endpoint.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """Versioned entities expose id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_journal(data: Dict[str, Any], label: str) -> None:
    """Append-only / immutable join entries expose only id and created_at.

    PRD §2.4 explicitly forbids updated_at and version on these.
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# RoomType (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_room_type(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "RoomType")
    assert isinstance(data["code"], str)
    assert data["code"] == data["code"].upper(), (
        f"RoomType.code must be uppercase, got {data['code']!r}"
    )
    assert 2 <= len(data["code"]) <= 8
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["base_rate_cents"], int)
    assert data["base_rate_cents"] >= 1000
    assert isinstance(data["max_occupancy"], int)
    assert 1 <= data["max_occupancy"] <= 10
    assert isinstance(data["total_physical_rooms"], int)
    assert data["total_physical_rooms"] >= 0
    assert data["status"] in {"ACTIVE", "RETIRED"}


# ---------------------------------------------------------------------------
# Room (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_room(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Room")
    assert isinstance(data["room_number"], str) and len(data["room_number"]) > 0
    assert is_valid_uuid(data["room_type_id"])
    assert data["housekeeping_status"] in {"VACANT_CLEAN", "OCCUPIED", "DIRTY"}
    assert data["operational_status"] in {"IN_SERVICE", "OUT_OF_ORDER"}
    assert data["lifecycle_status"] in {"ACTIVE", "ARCHIVED"}
    crid = data.get("current_reservation_id")
    if data["housekeeping_status"] == "OCCUPIED":
        assert crid is not None and is_valid_uuid(crid), (
            "Room.current_reservation_id must point to a UUID when OCCUPIED"
        )
    else:
        assert crid is None, (
            "PRD §3.1: 'for any other housekeeping status, "
            "[current_reservation_id] is null'"
        )


# ---------------------------------------------------------------------------
# MaintenanceBlock (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_maintenance_block(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "MaintenanceBlock")
    assert is_valid_uuid(data["room_id"])
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["end_date"] > data["start_date"], (
        "PRD §3.1: 'end_date must be strictly later than start_date.'"
    )
    assert isinstance(data.get("reason", ""), str)
    assert data["status"] in {"SCHEDULED", "ACTIVE", "RELEASED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Channel (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_channel(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Channel")
    assert isinstance(data["code"], str)
    assert data["code"] == data["code"].upper()
    assert data["channel_type"] in {"DIRECT", "OTA", "GDS", "WHOLESALER"}
    assert isinstance(data["commission_basis_points"], int)
    assert 0 <= data["commission_basis_points"] <= 5000
    assert isinstance(data["priority_rank"], int)
    assert data["priority_rank"] >= 1
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# RatePlan (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_rate_plan(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "RatePlan")
    assert isinstance(data["code"], str)
    assert data["code"] == data["code"].upper()
    assert is_valid_uuid(data["room_type_id"])
    assert data["refund_tier_code"] in {
        "FLEXIBLE", "MODERATE", "STRICT", "NON_REFUNDABLE",
    }
    assert isinstance(data["modification_allowed"], bool)
    assert data["status"] in {"ACTIVE", "RETIRED"}


# ---------------------------------------------------------------------------
# ChannelRatePlanMapping (PRD §2.4 — immutable join row, no updated_at/version)
# ---------------------------------------------------------------------------
def assert_channel_rate_plan_mapping(data: Dict[str, Any]) -> None:
    _assert_journal(data, "ChannelRatePlanMapping")
    assert "updated_at" not in data, (
        "PRD §2.4: 'ChannelRatePlanMapping ... carries only id and "
        "created_at — both updated_at and version are absent.'"
    )
    assert "version" not in data, (
        "PRD §2.4: 'ChannelRatePlanMapping ... carries only id and "
        "created_at — both updated_at and version are absent.'"
    )
    assert is_valid_uuid(data["channel_id"])
    assert is_valid_uuid(data["rate_plan_id"])
    assert isinstance(data["inventory_share_basis_points"], int)
    assert 0 <= data["inventory_share_basis_points"] <= 10000
    assert isinstance(data["enabled"], bool)


# ---------------------------------------------------------------------------
# RateOverride (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_rate_override(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "RateOverride")
    assert is_valid_uuid(data["room_type_id"])
    assert isinstance(data["stay_date"], str)
    assert isinstance(data["proposed_rate_cents"], int)
    assert data["proposed_rate_cents"] >= 1000
    assert data["recommendation_source"] in {"SYSTEM_ENGINE", "MANUAL_OVERRIDE"}
    assert data["status"] in {
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "SUPERSEDED",
    }
    if data["status"] == "APPROVED":
        # PRD §3.3: 'Approval ... sets applied_rate_cents equal to
        # proposed_rate_cents, captures the approving RevenueManager's
        # X-User-ID into approved_by.'
        assert data.get("applied_rate_cents") == data["proposed_rate_cents"], (
            f"RateOverride.applied_rate_cents must equal proposed_rate_cents "
            f"on APPROVED, got {data.get('applied_rate_cents')!r}"
        )
        assert isinstance(data.get("approved_by"), str)
        assert len(data["approved_by"]) > 0


# ---------------------------------------------------------------------------
# OverbookingPolicy (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_overbooking_policy(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "OverbookingPolicy")
    assert is_valid_uuid(data["room_type_id"])
    assert isinstance(data["stay_date"], str)
    assert isinstance(data["overbook_ratio_basis_points"], int)
    assert 0 <= data["overbook_ratio_basis_points"] <= 5000
    assert isinstance(data["estimated_no_show_probability_basis_points"], int)
    assert 0 <= data["estimated_no_show_probability_basis_points"] <= 10000
    assert isinstance(data["walkout_compensation_cents"], int)
    assert data["walkout_compensation_cents"] >= 0
    assert data["status"] in {"ACTIVE", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# Reservation (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_reservation(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Reservation")
    assert isinstance(data["guest_name"], str) and len(data["guest_name"]) > 0
    assert is_valid_uuid(data["room_type_id"])
    assert is_valid_uuid(data["rate_plan_id"])
    assert is_valid_uuid(data["channel_id"])
    assert isinstance(data["check_in_date"], str)
    assert isinstance(data["check_out_date"], str)
    assert data["check_out_date"] > data["check_in_date"], (
        "PRD §3.5: 'check_out_date MUST be strictly later than check_in_date.'"
    )
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert data["booking_status"] in {
        "PENDING", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT",
        "CANCELLED", "NO_SHOW", "WALKED_OUT",
    }
    assert data["payment_status"] in {
        "UNPAID", "AUTHORIZED", "CAPTURED",
        "REFUNDED_PARTIAL", "REFUNDED_FULL", "CHARGEBACK",
    }
    assert isinstance(data["booked_total_cents"], int)
    assert data["booked_total_cents"] >= 0
    assert isinstance(data["refund_amount_cents"], int)
    assert data["refund_amount_cents"] >= 0
    assert isinstance(data["no_show_charge_cents"], int)
    assert data["no_show_charge_cents"] >= 0
    assert isinstance(data["walkout_compensation_cents"], int)
    assert data["walkout_compensation_cents"] >= 0
    assert data["dispute_status"] in {
        "NONE", "OPEN", "RESOLVED_GUEST", "RESOLVED_HOTEL",
    }
    arid = data.get("assigned_room_id")
    if data["booking_status"] in {"CHECKED_IN", "CHECKED_OUT"}:
        assert arid is not None and is_valid_uuid(arid), (
            f"Reservation.assigned_room_id must be a UUID after check-in, "
            f"got {arid!r}"
        )


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.4 — append-only, no updated_at/version)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_journal(data, "AuditLog")
    assert "updated_at" not in data, (
        "PRD §2.4: 'an AuditLog event is an append-only event that likewise "
        "carries only id and created_at and never has an updated_at or "
        "version.'"
    )
    assert "version" not in data, (
        "PRD §2.4: 'an AuditLog event ... never has an updated_at or version.'"
    )
    assert data["event_type"] in {
        "RATE_OVERRIDE_APPROVED",
        "RATE_OVERRIDE_REJECTED",
        "OVERBOOKING_ACCEPTED",
        "WALKOUT_EXECUTED",
        "RATE_PARITY_VIOLATION_DETECTED",
    }
    assert isinstance(data["actor_role"], str) and len(data["actor_role"]) > 0
    assert isinstance(data["actor_id"], str) and len(data["actor_id"]) > 0
    assert isinstance(data["subject_entity"], str)
    assert isinstance(data["subject_id"], str)
    assert is_iso8601_timestamp(data["occurred_at"]), (
        f"AuditLog.occurred_at must be ISO 8601, got {data['occurred_at']!r}"
    )
    assert isinstance(data["payload"], dict)


# ---------------------------------------------------------------------------
# Walk-out cost estimate response (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_walkout_cost_estimate(data: Dict[str, Any]) -> None:
    """PRD §3.4: 'an object with the room_type_id, the stay_date, the
    projected expected_walkouts, and the projected estimated_cost_cents.'"""
    assert is_valid_uuid(data["room_type_id"])
    assert isinstance(data["stay_date"], str) and len(data["stay_date"]) > 0
    # PRD describes expected_walkouts as a projection (may be fractional).
    ew = data["expected_walkouts"]
    assert isinstance(ew, (int, float))
    assert ew >= 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] >= 0


# ---------------------------------------------------------------------------
# Helpers for audit log queries
# ---------------------------------------------------------------------------
def find_audit_logs(logs: Iterable[Dict[str, Any]],
                    *,
                    event_type: Optional[str] = None,
                    subject_id: Optional[str] = None,
                    subject_entity: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for log in logs:
        if event_type is not None and log.get("event_type") != event_type:
            continue
        if subject_id is not None and log.get("subject_id") != subject_id:
            continue
        if subject_entity is not None and log.get("subject_entity") != subject_entity:
            continue
        out.append(log)
    return out


__all__ = [
    "assert_room_type",
    "assert_room",
    "assert_maintenance_block",
    "assert_channel",
    "assert_rate_plan",
    "assert_channel_rate_plan_mapping",
    "assert_rate_override",
    "assert_overbooking_policy",
    "assert_reservation",
    "assert_audit_log",
    "assert_walkout_cost_estimate",
    "find_audit_logs",
]
