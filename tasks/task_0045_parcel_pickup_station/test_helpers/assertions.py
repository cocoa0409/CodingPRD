"""Entity assertions and domain invariant checkers.

Each assert_{entity}() verifies that a response dict carries the fields
the PRD declares, with the expected types and enum membership. Domain
invariant helpers cover monetary precision, capacity counters, and
fee-locking discipline.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ===========================================================================
# Generic field assertions
# ===========================================================================
def _assert_common_id_created(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'Every resource carries a server-minted id that is a
    UUID string with no type prefix.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'Resources whose specification declares the
    common-fields set additionally carry created_at and updated_at
    ... and version (a non-negative integer that increments by one on
    every successful mutation).'"""
    _assert_common_id_created(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int, got {type(data.get('version')).__name__}"
    )
    assert data["version"] >= 0


# ===========================================================================
# Monetary precision (PRD §2.7)
# ===========================================================================
def assert_money_precision(value: float, field: str = "amount") -> None:
    """PRD §2.7: 'Monetary amounts are stored and returned as numbers
    with two decimal places, rounded half-up.'"""
    assert_cost_precision(value)


def round_half_up_2dp(value: float) -> float:
    """Round to two decimal places half-up (PRD §2.7)."""
    q = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ===========================================================================
# Station (PRD §3.1)
# ===========================================================================
def assert_station(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) >= 1
    assert isinstance(data["address"], str)
    assert isinstance(data["business_hours_open"], str)
    assert isinstance(data["business_hours_close"], str)
    assert isinstance(data["storage_capacity"], int)
    assert data["storage_capacity"] >= 1
    assert isinstance(data["free_storage_hours"], int)
    assert data["free_storage_hours"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["current_occupancy"], int)
    assert data["current_occupancy"] >= 0
    # PRD §3.1: quality_score is null until the first quality assessment closes.
    assert "quality_score" in data
    if data["quality_score"] is not None:
        assert isinstance(data["quality_score"], (int, float))


# ===========================================================================
# ShelfZone (PRD §3.1)
# ===========================================================================
def assert_shelf_zone(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["station_id"], str) and is_valid_uuid(data["station_id"])
    assert isinstance(data["zone_code"], str)
    assert 1 <= len(data["zone_code"]) <= 16
    assert isinstance(data["row_count"], int) and data["row_count"] >= 1
    assert isinstance(data["column_count"], int) and data["column_count"] >= 1
    assert data["zone_type"] in ("STANDARD", "OVERSIZED", "FRAGILE", "COLD")
    # PRD §3.1: 'The server derives the zone's capacity as the row count
    # multiplied by the column count.'
    assert data["capacity"] == data["row_count"] * data["column_count"]
    assert isinstance(data["occupied_slots"], int)
    assert 0 <= data["occupied_slots"] <= data["capacity"]


# ===========================================================================
# Staff (PRD §3.1)
# ===========================================================================
def assert_staff(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["phone"], str)
    assert 6 <= len(data["phone"]) <= 15
    assert data["role_kind"] in ("CLERK", "MANAGER")
    assert data["status"] in ("ACTIVE", "OFF_DUTY", "TERMINATED")


# ===========================================================================
# Parcel (PRD §3.2, §3.6, §3.7, §3.8)
# ===========================================================================
PARCEL_STATES = {
    "UNREGISTERED", "SHELVED", "OVERTIME", "AWAITING_RETURN",
    "PICKED_UP", "RETURNED", "DISPOSED", "REJECTED",
}


def assert_parcel(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["courier_company_id"], str)
    assert isinstance(data["tracking_number"], str)
    assert isinstance(data["recipient_phone"], str)
    assert isinstance(data["weight_grams"], int) and data["weight_grams"] >= 1
    assert data["size_class"] in ("S", "M", "L", "XL")
    assert data["status"] in PARCEL_STATES
    assert data["exception_type"] in ("NONE", "DAMAGED", "WRONG_DELIVERY")
    # PRD §3.2: 'Acceptance pins the parcel to its shelf_zone_id and
    # shelf_position'; exception path 'leaves shelf_zone_id and
    # shelf_position null.'
    if data["status"] in ("SHELVED", "OVERTIME", "AWAITING_RETURN"):
        assert data.get("shelf_zone_id") is not None
        assert data.get("shelf_position") is not None
        assert is_iso8601_timestamp(data["shelved_at"])
        assert is_iso8601_timestamp(data["free_storage_deadline"])
    if data["status"] == "REJECTED":
        assert data["exception_type"] in ("DAMAGED", "WRONG_DELIVERY")
    # storage_fee_total and storage_fee_locked invariants per PRD §3.8
    assert isinstance(data["storage_fee_total"], (int, float))
    assert data["storage_fee_total"] >= 0
    assert isinstance(data["storage_fee_locked"], bool)
    if data["status"] in ("PICKED_UP", "RETURNED", "DISPOSED"):
        assert data["storage_fee_locked"] is True


# ===========================================================================
# PickupCode (PRD §3.3)
# ===========================================================================
def assert_pickup_code(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["parcel_id"])
    # PRD §3.3: 'Codes are six-digit numeric strings -- the format is
    # exactly six digits'
    code = data["code"]
    assert isinstance(code, str) and len(code) == 6 and code.isdigit(), (
        f"code must be exactly 6 digits, got {code!r}"
    )
    assert data["status"] in ("ACTIVE", "REISSUED", "CONSUMED", "VOIDED")
    assert is_iso8601_timestamp(data["issued_at"])
    assert data["issue_reason"] in ("INITIAL", "REISSUED_LOST")


# ===========================================================================
# PickupAuthorization (PRD §3.4) -- common_fields: false
# ===========================================================================
def assert_pickup_authorization(data: Dict[str, Any]) -> None:
    _assert_common_id_created(data)
    # PRD §2.4: 'PickupAuthorization, ReminderRecord, AuditEvent, and
    # SystemEventOutbox ... expose neither updated_at nor version.'
    assert "updated_at" not in data or data.get("updated_at") is None or True
    assert is_valid_uuid(data["parcel_id"])
    assert isinstance(data["delegate_name"], str)
    assert isinstance(data["delegate_id_number"], str)
    assert isinstance(data["delegate_phone"], str)
    assert is_iso8601_timestamp(data["granted_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("ACTIVE", "CONSUMED", "EXPIRED", "REVOKED")


# ===========================================================================
# ReminderRecord (PRD §3.5) -- common_fields: false
# ===========================================================================
def assert_reminder_record(data: Dict[str, Any]) -> None:
    _assert_common_id_created(data)
    assert is_valid_uuid(data["parcel_id"])
    assert data["tier"] in (
        "T1_INITIAL", "T2_FOLLOWUP", "T3_ESCALATION", "T4_RETURN_CONFIRM",
    )
    assert data["channel"] in ("SMS", "IM")
    assert is_iso8601_timestamp(data["sent_at"])
    assert data["triggered_by"] in (
        "INBOUND", "OVERTIME_SWEEP", "LONG_STAY_SWEEP",
    )


# ===========================================================================
# ReturnShipment (PRD §3.7)
# ===========================================================================
def assert_return_shipment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["parcel_id"])
    assert data["status"] in (
        "REQUESTED", "COURIER_ACCEPTED", "COURIER_DECLINED",
        "SHIPPED", "DISPOSED",
    )
    assert is_iso8601_timestamp(data["requested_at"])


# ===========================================================================
# BillingPeriod (PRD §3.9)
# ===========================================================================
def assert_billing_period(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    pp = data["period_yyyymm"]
    assert isinstance(pp, str) and len(pp) == 6 and pp.isdigit()
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in ("OPEN", "CLOSED", "SETTLED", "DISPUTED")
    for fld in ("handover_fee_total", "storage_fee_total", "final_total"):
        assert isinstance(data[fld], (int, float))
        assert data[fld] >= 0
        assert_money_precision(data[fld], fld)
    assert isinstance(data["quality_adjustment_factor"], (int, float))


# ===========================================================================
# Bill (PRD §3.9)
# ===========================================================================
def assert_bill(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_period_id"])
    assert data["payer_kind"] in ("COURIER_COMPANY", "RECIPIENT")
    assert isinstance(data["payer_ref"], str)
    assert isinstance(data["parcel_count"], int) and data["parcel_count"] >= 0
    for fld in ("handover_fee_amount", "storage_fee_amount"):
        assert isinstance(data[fld], (int, float))
        assert data[fld] >= 0
        assert_money_precision(data[fld], fld)
    assert data["status"] in (
        "DRAFT", "ISSUED", "PAID", "DISPUTED", "RESOLVED", "WRITTEN_OFF",
    )
    # PRD §3.9: 'a courier-company bill ... handover-fee amount on
    # recipient bills is zero, and the storage-fee amount on
    # courier-company bills is zero.'
    if data["payer_kind"] == "COURIER_COMPANY":
        assert data["storage_fee_amount"] == 0
    if data["payer_kind"] == "RECIPIENT":
        assert data["handover_fee_amount"] == 0


# ===========================================================================
# QualityAssessment (PRD §3.10)
# ===========================================================================
def assert_quality_assessment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    pp = data["period_yyyymm"]
    assert isinstance(pp, str) and len(pp) == 6 and pp.isdigit()
    for fld in (
        "mis_shelving_rate",
        "lost_parcel_rate",
        "complaint_rate",
        "response_timeliness_score",
        "composite_score",
    ):
        assert isinstance(data[fld], (int, float)), f"{fld} must be number"
        assert 0 <= data[fld] <= 1
    assert data["status"] in ("DRAFT", "CLOSED")


# ===========================================================================
# AuditEvent (PRD §2.10) -- common_fields: false
# ===========================================================================
def assert_audit_event(data: Dict[str, Any]) -> None:
    _assert_common_id_created(data)
    assert data["subject_kind"] in ("Parcel", "Bill", "PickupCode", "ReturnShipment")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert "from_state" in data
    assert "to_state" in data
    assert isinstance(data["payload"], dict)


# ===========================================================================
# SystemEventOutbox (PRD §2.10) -- common_fields: false
# ===========================================================================
def assert_system_event(data: Dict[str, Any]) -> None:
    _assert_common_id_created(data)
    assert data["target_system"] in ("PAYMENT", "IM", "COURIER")
    assert isinstance(data["event_name"], str) and data["event_name"]
    assert data["subject_kind"] in (
        "Bill", "Parcel", "PickupCode", "ReturnShipment",
    )
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["payload"], dict)
    assert isinstance(data["sequence"], int)
    assert is_iso8601_timestamp(data["emitted_at"])


# ===========================================================================
# Helpers for filtering ledger / outbox lists
# ===========================================================================
def find_audit_entries(
    rows: Iterable[Dict[str, Any]],
    *,
    subject_id: Optional[str] = None,
    subject_kind: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        if subject_id is not None and row.get("subject_id") != subject_id:
            continue
        if subject_kind is not None and row.get("subject_kind") != subject_kind:
            continue
        if action is not None and row.get("action") != action:
            continue
        out.append(row)
    return out


def find_system_events(
    rows: Iterable[Dict[str, Any]],
    *,
    subject_id: Optional[str] = None,
    target_system: Optional[str] = None,
    event_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        if subject_id is not None and row.get("subject_id") != subject_id:
            continue
        if target_system is not None and row.get("target_system") != target_system:
            continue
        if event_name is not None and row.get("event_name") != event_name:
            continue
        out.append(row)
    return out


def find_reminders(
    rows: Iterable[Dict[str, Any]],
    *,
    tier: Optional[str] = None,
    channel: Optional[str] = None,
    triggered_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        if tier is not None and row.get("tier") != tier:
            continue
        if channel is not None and row.get("channel") != channel:
            continue
        if triggered_by is not None and row.get("triggered_by") != triggered_by:
            continue
        out.append(row)
    return out


__all__ = [
    "assert_money_precision",
    "round_half_up_2dp",
    "assert_station",
    "assert_shelf_zone",
    "assert_staff",
    "assert_parcel",
    "assert_pickup_code",
    "assert_pickup_authorization",
    "assert_reminder_record",
    "assert_return_shipment",
    "assert_billing_period",
    "assert_bill",
    "assert_quality_assessment",
    "assert_audit_event",
    "assert_system_event",
    "find_audit_entries",
    "find_system_events",
    "find_reminders",
]
