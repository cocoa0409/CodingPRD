"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares; computed-field
presence is asserted only when PRD §3 explicitly states the field is
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
    """Append-only journal entries expose only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# ParkingLot (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_parking_lot(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ParkingLot")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str) and len(data["timezone"]) > 0
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["hourly_rate_cents"] >= 0
    assert isinstance(data["daily_cap_cents"], int)
    assert data["daily_cap_cents"] >= 0
    assert isinstance(data["free_minutes"], int) and data["free_minutes"] >= 0
    assert isinstance(data["tow_grace_minutes"], int)
    assert data["tow_grace_minutes"] >= 0
    assert isinstance(data["reservation_hold_minutes"], int)
    assert data["reservation_hold_minutes"] >= 0
    assert isinstance(data["no_show_penalty_cents"], int)
    assert data["no_show_penalty_cents"] >= 0
    assert isinstance(data["partner_share_bps"], int)
    assert 0 <= data["partner_share_bps"] <= 10000


# ---------------------------------------------------------------------------
# Zone (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_zone(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Zone")
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["zone_type"] in {"STANDARD", "VIP", "DISABLED", "EMERGENCY"}
    assert isinstance(data["total_spaces"], int) and data["total_spaces"] >= 0
    assert isinstance(data["free_spaces"], int) and data["free_spaces"] >= 0
    assert data["free_spaces"] <= data["total_spaces"]


# ---------------------------------------------------------------------------
# Space (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_space(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Space")
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["occupancy_status"] in {"FREE", "OCCUPIED"}
    assert data["reservation_lock"] in {"UNRESERVED", "RESERVED"}
    cur = data.get("current_session_id")
    assert cur is None or is_valid_uuid(cur)
    last_exited = data.get("last_exited_at")
    if last_exited is not None:
        assert is_iso8601_timestamp(last_exited)


# ---------------------------------------------------------------------------
# Vehicle (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_vehicle(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Vehicle")
    assert isinstance(data["plate"], str) and 1 <= len(data["plate"]) <= 12
    # PRD §3.2: normalized to uppercase, [A-Z0-9-]
    assert data["plate"] == data["plate"].upper()
    assert " " not in data["plate"]
    assert data["kind"] in {"REGULAR", "EMERGENCY", "DISABLED"}
    assert isinstance(data["binding_eligible"], bool)
    assert isinstance(data["open_violation_count"], int)
    assert data["open_violation_count"] >= 0


# ---------------------------------------------------------------------------
# Card (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_card(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Card")
    assert data["card_type"] in {"MONTHLY", "STORED_VALUE"}
    assert data["status"] in {"ACTIVE", "SUSPENDED", "EXPIRED"}
    assert isinstance(data["holder_ref"], str)
    assert isinstance(data["balance_cents"], int)
    # PRD §3.3: balance_cents is provisional; finalized_balance_cents companion
    assert isinstance(data["finalized_balance_cents"], int)
    # finalized never exceeds provisional (PRD §3.3)
    assert data["finalized_balance_cents"] <= data["balance_cents"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert data["monthly_fee_cents"] >= 0
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert isinstance(data["bound_vehicle_ids"], list)
    for vid in data["bound_vehicle_ids"]:
        assert is_valid_uuid(vid)
    assert isinstance(data["auto_pay_enabled"], bool)


# ---------------------------------------------------------------------------
# Session (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_session(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Session")
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["space_id"])
    assert is_valid_uuid(data["vehicle_id"])
    if data.get("card_id") is not None:
        assert is_valid_uuid(data["card_id"])
    if data.get("reservation_id") is not None:
        assert is_valid_uuid(data["reservation_id"])
    assert data["occupancy_status"] in {"ACTIVE", "EXITED"}
    assert data["payment_status"] in {"UNPAID", "PAID", "WAIVED", "DISPUTED"}
    assert is_iso8601_timestamp(data["entry_at"])
    if data["occupancy_status"] == "EXITED":
        # PRD §3.5: exit_at is pinned at exit transition
        assert is_iso8601_timestamp(data.get("exit_at", "")), (
            "EXITED Session must carry pinned exit_at"
        )
        # PRD §3.5: final_fee_cents pinned at exit transition
        assert isinstance(data.get("final_fee_cents"), int), (
            "EXITED Session must carry pinned final_fee_cents"
        )
        # PRD §3.5: billing_kind pinned at exit transition
        assert data.get("billing_kind") in {
            "HOURLY", "MONTHLY_COVERED", "EXEMPT_VEHICLE"
        }


# ---------------------------------------------------------------------------
# Reservation (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_reservation(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Reservation")
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["zone_id"])
    if data.get("space_id") is not None:
        assert is_valid_uuid(data["space_id"])
    assert is_valid_uuid(data["vehicle_id"])
    if data.get("card_id") is not None:
        assert is_valid_uuid(data["card_id"])
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert data["status"] in {
        "HELD", "MATCHED", "EXPIRED_NO_SHOW", "CANCELLED"
    }
    if data.get("matched_session_id") is not None:
        assert is_valid_uuid(data["matched_session_id"])
    assert isinstance(data["penalty_charged_cents"], int)
    assert data["penalty_charged_cents"] >= 0


# ---------------------------------------------------------------------------
# Violation (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_violation(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Violation")
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["vehicle_id"])
    if data.get("session_id") is not None:
        assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["space_id"])
    assert data["violation_type"] in {
        "OVERSTAY", "NON_PAYING", "BLOCKING", "WRONG_ZONE"
    }
    assert data["status"] in {"PENDING", "PAID", "DISPUTED", "TOWED_AWAY"}
    assert isinstance(data["officer_id"], str) and len(data["officer_id"]) > 0
    assert is_iso8601_timestamp(data["detected_at"])


# ---------------------------------------------------------------------------
# Fine (PRD §3.6) — append-only journal
# ---------------------------------------------------------------------------
def assert_fine(data: Dict[str, Any]) -> None:
    _assert_journal(data, "Fine")
    assert is_valid_uuid(data["violation_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    components = data["components"]
    assert isinstance(components, dict)
    assert isinstance(components.get("base_cents"), int)
    assert isinstance(components.get("type_multiplier"), (int, float))
    assert isinstance(
        components.get("repeat_offender_surcharge_cents"), int
    )
    assert isinstance(
        components.get("photo_required_surcharge_cents"), int
    )
    paid_at = data.get("paid_at")
    if paid_at is not None:
        assert is_iso8601_timestamp(paid_at)


# ---------------------------------------------------------------------------
# Payment (PRD §3.7) — append-only journal
# ---------------------------------------------------------------------------
def assert_payment(data: Dict[str, Any]) -> None:
    _assert_journal(data, "Payment")
    assert data["kind"] in {
        "SESSION_FEE", "FINE_PAYMENT", "CARD_RECHARGE",
        "NO_SHOW_PENALTY", "REFUND",
    }
    assert is_valid_uuid(data["subject_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0  # PRD §3.7: positive
    if data.get("card_id") is not None:
        assert is_valid_uuid(data["card_id"])
    assert is_iso8601_timestamp(data["processed_at"])


# ---------------------------------------------------------------------------
# RevenueEntry (PRD §3.7) — append-only journal
# ---------------------------------------------------------------------------
def assert_revenue_entry(data: Dict[str, Any]) -> None:
    _assert_journal(data, "RevenueEntry")
    assert is_valid_uuid(data["lot_id"])
    if data.get("zone_id") is not None:
        assert is_valid_uuid(data["zone_id"])
    assert data["billing_type"] in {
        "HOURLY", "MONTHLY", "RESERVATION", "NO_SHOW_PENALTY",
        "FINE", "REFUND", "ADJUSTMENT",
    }
    assert data["source_kind"] in {
        "SESSION", "RESERVATION", "VIOLATION", "CARD", "MANUAL"
    }
    assert is_valid_uuid(data["source_id"])
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["partner_share_cents"], int)
    # PRD §3.7: 'partner_share_cents is always non-negative'
    assert data["partner_share_cents"] >= 0
    assert isinstance(data["house_share_cents"], int)
    # PRD §3.7: 'house_share_cents = gross_amount_cents - partner_share_cents'
    assert (
        data["house_share_cents"] + data["partner_share_cents"]
        == data["gross_amount_cents"]
    )
    assert isinstance(data["settlement_period"], str)
    assert len(data["settlement_period"]) == 10  # YYYY-MM-DD


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.11) — append-only journal
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_journal(data, "AuditLog")
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert data["action"] in {
        "BILLING_ADJUSTMENT", "RESERVATION_CHANGE",
        "FINE_WAIVE", "CARD_TRANSFER",
    }
    assert isinstance(data["subject_kind"], str)
    assert isinstance(data["subject_id"], str)
    assert isinstance(data.get("before"), dict)
    assert isinstance(data.get("after"), dict)
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def find_audit_logs(
    logs: Iterable[Dict[str, Any]],
    *,
    action: Optional[str] = None,
    subject_id: Optional[str] = None,
    subject_kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter an audit-log list by any combination of action / subject."""
    out: List[Dict[str, Any]] = []
    for entry in logs:
        if action is not None and entry.get("action") != action:
            continue
        if subject_id is not None and entry.get("subject_id") != subject_id:
            continue
        if subject_kind is not None and entry.get("subject_kind") != subject_kind:
            continue
        out.append(entry)
    return out


def assert_revenue_entries_for_lot(
    entries: Iterable[Dict[str, Any]],
    lot_id: str,
) -> None:
    for e in entries:
        assert e["lot_id"] == lot_id, (
            f"RevenueEntry {e['id']} has lot_id={e['lot_id']!r}, "
            f"expected {lot_id!r}"
        )


__all__ = [
    "assert_parking_lot",
    "assert_zone",
    "assert_space",
    "assert_vehicle",
    "assert_card",
    "assert_session",
    "assert_reservation",
    "assert_violation",
    "assert_fine",
    "assert_payment",
    "assert_revenue_entry",
    "assert_audit_log",
    "find_audit_logs",
    "assert_revenue_entries_for_lot",
]
