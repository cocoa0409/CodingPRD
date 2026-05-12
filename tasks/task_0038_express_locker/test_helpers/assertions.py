"""Entity assertions and domain invariant checkers.

Each `assert_<entity>` validates the surface-level shape of a serialized
entity per PRD §2.4 and §3 — id present + UUID; created_at present + ISO
8601 UTC; entity-specific fields with PRD-exact names; status drawn from
PRD-named enum values.

Append-only entities (PickupCodeAttempt, CompartmentEvent, AuditLog) per
PRD §2.4 carry only id + created_at; their assertions intentionally do
NOT require updated_at or version.
"""
from __future__ import annotations
import math
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AuditAction,
    CapacityWarningLevel,
    CompartmentEventType,
    CompartmentSize,
    CompartmentStatus,
    CorrectionOrigin,
    CourierBlacklistStatus,
    DisputeClaimType,
    DisputeStatus,
    FeeWaiverReason,
    LockerMachineOnlineStatus,
    OvertimeFeePaymentStatus,
    OvertimeFeeVariant,
    ParcelStatus,
    PickupAttemptFailureReason,
    PickupMethod,
    SettlementStatus,
)


# ---------------------------------------------------------------------------
# Common-fields checks (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    assert "id" in data, f"{entity}.id missing"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be a UUID with no type prefix (PRD §2.4); got "
        f"{data['id']!r}"
    )
    assert "created_at" in data, f"{entity}.created_at missing"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"{entity}.created_at must be ISO 8601 UTC (PRD §2.4); got "
        f"{data['created_at']!r}"
    )
    assert "updated_at" in data, f"{entity}.updated_at missing"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"{entity}.updated_at must be ISO 8601 UTC (PRD §2.4); got "
        f"{data['updated_at']!r}"
    )
    assert "version" in data, f"{entity}.version missing"
    assert isinstance(data["version"], int) and data["version"] >= 0, (
        f"{entity}.version must be non-negative integer (PRD §2.4); got "
        f"{data.get('version')!r}"
    )


def _assert_event_log_fields(data: Dict[str, Any], entity: str) -> None:
    """Append-only entities carry ONLY id + created_at (PRD §2.4)."""
    assert "id" in data, f"{entity}.id missing"
    assert is_valid_uuid(data["id"]), f"{entity}.id must be a UUID"
    assert "created_at" in data, f"{entity}.created_at missing"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"{entity}.created_at must be ISO 8601 UTC (PRD §2.4)"
    )


# ---------------------------------------------------------------------------
# LockerMachine (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
def assert_locker_machine(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "LockerMachine")
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["partner_id"], str) and data["partner_id"]
    assert isinstance(data["firmware_version"], str) and data["firmware_version"]
    assert data["online_status"] in {e.value for e in LockerMachineOnlineStatus}
    assert isinstance(data["degraded_mode"], bool)
    assert isinstance(data["total_compartments"], int)
    assert isinstance(data["occupied_count_small"], int)
    assert isinstance(data["occupied_count_medium"], int)
    assert isinstance(data["occupied_count_large"], int)
    assert data["capacity_warning_level"] in {
        e.value for e in CapacityWarningLevel
    }


# ---------------------------------------------------------------------------
# Compartment (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_compartment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Compartment")
    assert is_valid_uuid(data["locker_machine_id"]), (
        "Compartment.locker_machine_id must be UUID"
    )
    assert isinstance(data["slot_label"], str) and data["slot_label"]
    assert data["size"] in {e.value for e in CompartmentSize}
    assert data["status"] in {e.value for e in CompartmentStatus}


# ---------------------------------------------------------------------------
# Courier (PRD §3.10)
# ---------------------------------------------------------------------------
def assert_courier(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Courier")
    assert isinstance(data["phone"], str) and data["phone"]
    assert isinstance(data["company_id"], str) and data["company_id"]
    assert data["blacklist_status"] in {
        e.value for e in CourierBlacklistStatus
    }
    bl_reason = data.get("blacklist_reason")
    if data["blacklist_status"] == CourierBlacklistStatus.ACTIVE.value:
        # PRD §3.10: 'new couriers start in blacklist_status = ACTIVE with
        # blacklist_reason of null.' We only assert the steady-state ACTIVE
        # rule; transitional states may legitimately carry a reason cleared
        # by reinstate.
        assert bl_reason is None or bl_reason == "", (
            f"Courier.blacklist_reason should be null when ACTIVE; got "
            f"{bl_reason!r}"
        )
    else:
        assert isinstance(bl_reason, str) and bl_reason, (
            f"Courier.blacklist_reason required when not ACTIVE; got "
            f"{bl_reason!r}"
        )


# ---------------------------------------------------------------------------
# Parcel (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
def assert_parcel(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Parcel")
    assert isinstance(data["tracking_no"], str) and data["tracking_no"]
    assert is_valid_uuid(data["courier_id"]), "Parcel.courier_id must be UUID"
    assert is_valid_uuid(data["locker_machine_id"]), (
        "Parcel.locker_machine_id must be UUID"
    )
    if data.get("compartment_id") is not None:
        assert is_valid_uuid(data["compartment_id"])
    assert isinstance(data["recipient_phone"], str)
    assert data["required_size"] in {e.value for e in CompartmentSize}
    assert data["status"] in {e.value for e in ParcelStatus}
    assert isinstance(data["failed_open_attempts"], int) and (
        data["failed_open_attempts"] >= 0
    )
    if data.get("replaces_parcel_id") is not None:
        assert is_valid_uuid(data["replaces_parcel_id"])
    assert data["correction_origin"] in {e.value for e in CorrectionOrigin}
    assert isinstance(data["fee_waived"], bool)
    assert data["fee_waiver_reason"] in {e.value for e in FeeWaiverReason}
    # provisional/final fees are integers (cents) per PRD §3.5 / §2.8
    if data.get("provisional_overtime_fee") is not None:
        assert isinstance(data["provisional_overtime_fee"], int)
    if data.get("final_overtime_fee") is not None:
        assert isinstance(data["final_overtime_fee"], int)


# ---------------------------------------------------------------------------
# OvertimeFeeRecord (PRD §3.5, §3.8)
# ---------------------------------------------------------------------------
def assert_overtime_fee_record(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "OvertimeFeeRecord")
    assert is_valid_uuid(data["parcel_id"])
    assert data["variant"] in {e.value for e in OvertimeFeeVariant}
    assert is_iso8601_timestamp(data["cutoff_at"]), (
        "OvertimeFeeRecord.cutoff_at must be ISO 8601 UTC"
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["payment_status"] in {
        e.value for e in OvertimeFeePaymentStatus
    }


# ---------------------------------------------------------------------------
# Dispute (PRD §3.9)
# ---------------------------------------------------------------------------
def assert_dispute(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Dispute")
    assert is_valid_uuid(data["parcel_id"])
    assert data["claim_type"] in {e.value for e in DisputeClaimType}
    assert data["status"] in {e.value for e in DisputeStatus}
    assert isinstance(data["outcome_amount_cents"], int)
    assert data["outcome_amount_cents"] >= 0


# ---------------------------------------------------------------------------
# SettlementBatch (PRD §3.11)
# ---------------------------------------------------------------------------
def assert_settlement_batch(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SettlementBatch")
    assert isinstance(data["partner_id"], str) and data["partner_id"]
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["gross_overtime_revenue_cents"], int)
    assert isinstance(data["refund_reversal_cents"], int)
    assert isinstance(data["net_revenue_cents"], int)
    assert isinstance(data["partner_share_cents"], int)
    assert isinstance(data["platform_share_cents"], int)
    assert data["status"] in {e.value for e in SettlementStatus}
    # PRD §3.11 invariant: partner + platform == net (no drift)
    assert (
        data["partner_share_cents"] + data["platform_share_cents"]
        == data["net_revenue_cents"]
    ), (
        "SettlementBatch invariant broken: partner_share_cents + "
        "platform_share_cents must equal net_revenue_cents"
    )
    assert (
        data["net_revenue_cents"]
        == data["gross_overtime_revenue_cents"] - data["refund_reversal_cents"]
    ), "SettlementBatch.net_revenue_cents = gross - refund_reversal (PRD §3.11)"


# ---------------------------------------------------------------------------
# Append-only logs (PRD §2.4, §2.10)
# ---------------------------------------------------------------------------
def assert_pickup_code_attempt(data: Dict[str, Any]) -> None:
    _assert_event_log_fields(data, "PickupCodeAttempt")
    assert is_valid_uuid(data["parcel_id"])
    assert data["method"] in {e.value for e in PickupMethod}
    assert isinstance(data["success"], bool)
    assert data["failure_reason"] in {
        e.value for e in PickupAttemptFailureReason
    }


def assert_compartment_event(data: Dict[str, Any]) -> None:
    _assert_event_log_fields(data, "CompartmentEvent")
    assert is_valid_uuid(data["compartment_id"])
    pid = data.get("parcel_id")
    if pid is not None:
        assert is_valid_uuid(pid)
    # PRD §2.10: actor_role ∈ {Courier, Recipient, OperationsAdmin, system}
    assert data["actor_role"] in {
        "Courier", "Recipient", "OperationsAdmin", "system",
    }
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert data["event_type"] in {e.value for e in CompartmentEventType}


def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_event_log_fields(data, "AuditLog")
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert data["action"] in {e.value for e in AuditAction}
    assert isinstance(data["subject_entity"], str) and data["subject_entity"]
    assert "subject_id" in data
    assert "payload" in data and isinstance(data["payload"], dict)


def find_audit_actions(
    entries: Iterable[Dict[str, Any]],
    *,
    action: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter audit entries by action and/or subject_id (PRD §2.10)."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if action is not None and e.get("action") != action:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_capacity_invariant(machine: Dict[str, Any]) -> None:
    """LockerMachine occupancy fields are non-negative and the warning level
    is one of the three values named in PRD §3.2."""
    assert machine["occupied_count_small"] >= 0
    assert machine["occupied_count_medium"] >= 0
    assert machine["occupied_count_large"] >= 0
    assert machine["total_compartments"] >= 0
    assert machine["capacity_warning_level"] in {
        CapacityWarningLevel.NORMAL.value,
        CapacityWarningLevel.NEAR_FULL.value,
        CapacityWarningLevel.FULL_BLOCK_DEPOSITS.value,
    }


def assert_amount_cents(value: Any, *, label: str = "amount_cents") -> None:
    """PRD §2.8: 'All overtime amounts are tracked as integer cents'."""
    assert isinstance(value, int), (
        f"{label} must be integer cents (PRD §2.8); got {type(value).__name__}"
    )
    assert value >= 0, f"{label} must be non-negative; got {value}"


def assert_rate_4dp(value: Any, *, label: str) -> None:
    """PRD §3.10: rates reported to four decimal places."""
    assert isinstance(value, (int, float))
    if isinstance(value, float):
        # Value rounded to 4 decimals must match itself within float tolerance.
        rounded = round(value, 4)
        assert math.isclose(value, rounded, abs_tol=1e-9), (
            f"{label} must be 4-decimal precision (PRD §3.10); got {value}"
        )


__all__ = [
    "assert_locker_machine",
    "assert_compartment",
    "assert_courier",
    "assert_parcel",
    "assert_overtime_fee_record",
    "assert_dispute",
    "assert_settlement_batch",
    "assert_pickup_code_attempt",
    "assert_compartment_event",
    "assert_audit_log",
    "find_audit_actions",
    "assert_capacity_invariant",
    "assert_amount_cents",
    "assert_rate_4dp",
]
