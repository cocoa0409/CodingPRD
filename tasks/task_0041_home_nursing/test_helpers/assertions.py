"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks are pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares -- never more, never
less.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """Standard resources expose id, created_at, updated_at, version
    (PRD §2.4)."""
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


def _assert_append_only(data: Dict[str, Any], label: str) -> None:
    """Append-only entries (CertificationRecord, Dispatch, WasteEntry,
    AuditLog, PayoutBatch) expose only id and created_at per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Nurse (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_nurse(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Nurse")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["gender"] in {"M", "F", "O"}, (
        f"Nurse.gender must be one of M|F|O, got {data.get('gender')!r}"
    )
    assert isinstance(data["languages"], list)
    assert isinstance(data["license_number"], str)
    assert isinstance(data["license_verified"], bool)
    assert isinstance(data["hospital_affiliation_verified"], bool)
    assert isinstance(data["specialty_tags"], list)
    for tag in data["specialty_tags"]:
        assert tag in {
            "WOUND_CARE", "IV_INFUSION", "CATHETER_CARE",
            "MATERNAL_NEWBORN", "ELDERLY_CARE", "PALLIATIVE",
        }, f"Unknown specialty_tag: {tag!r}"
    assert isinstance(data["home_lat"], (int, float))
    assert -90 <= data["home_lat"] <= 90
    assert isinstance(data["home_lng"], (int, float))
    assert -180 <= data["home_lng"] <= 180
    assert isinstance(data["max_daily_orders"], int)
    assert data["max_daily_orders"] >= 1
    assert isinstance(data["revenue_share_bps"], int)
    rating = data["rating"]
    assert isinstance(rating, (int, float))
    assert 1.00 <= float(rating) <= 5.00, (
        f"Nurse.rating must be in [1.00, 5.00], got {rating!r}"
    )
    assert data["certification_status"] in {
        "PENDING", "CERTIFIED", "EXPIRING", "DISQUALIFIED",
    }
    cu = data.get("certified_until")
    assert cu is None or is_iso8601_timestamp(cu), (
        f"Nurse.certified_until must be ISO 8601 or null, got {cu!r}"
    )


# ---------------------------------------------------------------------------
# CertificationRecord (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_certification_record(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "CertificationRecord")
    assert data["kind"] in {
        "INITIAL", "RECERTIFICATION", "TRAINING", "DISQUALIFICATION",
    }
    assert isinstance(data.get("training_hours", 0), (int, float))
    assert float(data.get("training_hours", 0)) >= 0
    assert data["outcome"] in {"PASS", "FAIL"}
    assert is_iso8601_timestamp(data["effective_at"])
    assert isinstance(data["nurse_id"], str) and data["nurse_id"]


# ---------------------------------------------------------------------------
# ServiceItem (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_service_item(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ServiceItem")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert data["required_skill"] in {
        "WOUND_CARE", "IV_INFUSION", "CATHETER_CARE",
        "MATERNAL_NEWBORN", "ELDERLY_CARE", "PALLIATIVE",
    }
    assert isinstance(data["requires_medical_doc"], bool)
    assert isinstance(data["requires_eligibility_review"], bool)
    assert isinstance(data["base_price_cents"], int)
    assert data["base_price_cents"] >= 0
    assert isinstance(data["duration_minutes"], int)
    assert data["duration_minutes"] > 0
    assert isinstance(data["active"], bool)


# ---------------------------------------------------------------------------
# Order (PRD §3.2 - §3.5)
# ---------------------------------------------------------------------------
def assert_order(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Order")
    assert isinstance(data["patient_id"], str) and data["patient_id"]
    assert isinstance(data["service_item_code"], str)
    assert isinstance(data["service_lat"], (int, float))
    assert isinstance(data["service_lng"], (int, float))
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert data["preferred_gender"] in {"M", "F", "ANY"}
    assert isinstance(data["preferred_language"], str)
    assert data["status"] in {
        "SUBMITTED", "UNDER_REVIEW", "AWAITING_DISPATCH", "DISPATCHED",
        "IN_PROGRESS", "COMPLETED", "CANCELLED", "REJECTED",
    }
    assert data["payment_status"] in {
        "UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED",
    }
    assert isinstance(data["dispatch_attempt_count"], int)
    assert data["dispatch_attempt_count"] >= 0
    if data.get("estimated_fee_cents") is not None:
        assert isinstance(data["estimated_fee_cents"], int)
        assert data["estimated_fee_cents"] >= 0
    if data.get("final_fee_cents") is not None:
        assert isinstance(data["final_fee_cents"], int)
        assert data["final_fee_cents"] >= 0


# ---------------------------------------------------------------------------
# Dispatch (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_dispatch(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "Dispatch")
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert isinstance(data["nurse_id"], str) and data["nurse_id"]
    assert isinstance(data["distance_km"], (int, float))
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["accept_deadline"])
    assert data["status"] in {
        "OFFERED", "ACCEPTED", "REJECTED", "EXPIRED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# ServiceRecord (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_service_record(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ServiceRecord")
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert isinstance(data["nurse_id"], str) and data["nurse_id"]
    assert is_iso8601_timestamp(data["checkin_at"])
    assert isinstance(data["checkin_lat"], (int, float))
    assert isinstance(data["checkin_lng"], (int, float))
    assert isinstance(data["face_verification_passed"], bool)
    assert data["status"] in {
        "STARTED", "IN_PROGRESS", "AWAITING_PATIENT_CONFIRM", "COMPLETED",
    }


# ---------------------------------------------------------------------------
# WasteEntry (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_waste_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "WasteEntry")
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert data["category"] in {"SHARPS", "INFECTIOUS", "PHARMACEUTICAL"}
    assert isinstance(data["quantity"], (int, float))
    assert float(data["quantity"]) > 0
    assert data["unit"] in {"PCS", "LITERS", "KG"}
    assert data["status"] in {"REGISTERED", "HANDED_OVER", "ARCHIVED"}


# ---------------------------------------------------------------------------
# Package (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_package(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Package")
    assert isinstance(data["patient_id"], str) and data["patient_id"]
    assert isinstance(data["service_item_code"], str)
    assert isinstance(data["total_credits"], int)
    assert data["total_credits"] > 0
    assert isinstance(data["used_credits"], int)
    assert data["used_credits"] >= 0
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in {"ACTIVE", "EXHAUSTED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Settlement (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_settlement(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "Settlement")
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert isinstance(data["gross_fee_cents"], int)
    assert data["gross_fee_cents"] >= 0
    assert isinstance(data["distance_surcharge_cents"], int)
    assert isinstance(data["time_of_day_surcharge_cents"], int)
    assert isinstance(data["package_deduction_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert data["tax_cents"] >= 0
    assert isinstance(data["nurse_revenue_share_cents"], int)
    assert isinstance(data["platform_share_cents"], int)
    assert data["status"] in {
        "PENDING", "FINALIZED", "PAID_OUT", "REVERSED",
    }


# ---------------------------------------------------------------------------
# Complaint (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_complaint(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Complaint")
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert data["category"] in {
        "NURSE_MISCONDUCT", "SERVICE_QUALITY", "BILLING", "SAFETY", "OTHER",
    }
    assert data["stage"] in {
        "SUBMITTED", "TRIAGE", "MEDIATION", "RESOLVED", "REJECTED",
    }
    if data.get("routing") is not None:
        assert data["routing"] in {"NURSE_RELATED", "SERVICE_RELATED"}


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.9)
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditLog")
    assert data["subject_type"] in {
        "ORDER", "SERVICE_RECORD", "COMPLAINT", "NURSE",
    }
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["action"], str) and data["action"]


# ---------------------------------------------------------------------------
# PayoutBatch (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_payout_batch(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "PayoutBatch")
    assert is_iso8601_timestamp(data["cutoff_at"])
    assert isinstance(data["total_settlements"], int)
    assert data["total_settlements"] >= 0
    assert isinstance(data["total_nurse_share_cents"], int)
    assert isinstance(data["total_platform_share_cents"], int)
    assert data["status"] in {"BUILDING", "PAID"}


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_settlement_invariants(data: Dict[str, Any]) -> None:
    """PRD §3.5: 'platform_share_cents is the gross minus the nurse share'.
    PRD §2.7: 'all monetary fields are stored as integer cents'."""
    assert isinstance(data["gross_fee_cents"], int)
    assert isinstance(data["nurse_revenue_share_cents"], int)
    assert isinstance(data["platform_share_cents"], int)
    assert (
        data["nurse_revenue_share_cents"] + data["platform_share_cents"]
        == data["gross_fee_cents"]
    ), (
        "Settlement.platform_share_cents must equal gross - nurse share, "
        f"got nurse={data['nurse_revenue_share_cents']}, "
        f"platform={data['platform_share_cents']}, "
        f"gross={data['gross_fee_cents']}"
    )


def find_audit_entries(
    audit_logs: Iterable[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in audit_logs:
        if subject_type is not None and row.get("subject_type") != subject_type:
            continue
        if subject_id is not None and row.get("subject_id") != subject_id:
            continue
        if action is not None and row.get("action") != action:
            continue
        out.append(row)
    return out


__all__ = [
    "assert_nurse",
    "assert_certification_record",
    "assert_service_item",
    "assert_order",
    "assert_dispatch",
    "assert_service_record",
    "assert_waste_entry",
    "assert_package",
    "assert_settlement",
    "assert_complaint",
    "assert_audit_log_entry",
    "assert_payout_batch",
    "assert_settlement_invariants",
    "find_audit_entries",
]
