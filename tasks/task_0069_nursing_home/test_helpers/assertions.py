"""Per-entity assertions and domain-invariant checkers.

Each ``assert_<entity>`` checks the field surface the PRD declares.
Append-only entities (CareTaskExecution, MedicationAdministration,
MedicationErrorReport, AuditLog, ExternalEvent, WaitlistEntry) MUST NOT
carry ``updated_at`` or ``version`` (PRD §2.4).
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common envelope helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 — id is a UUID without prefix; created_at/updated_at are ISO 8601
    UTC strings; version is an integer starting at 1, bumped on every successful
    mutation."""
    assert is_valid_uuid(str(data.get("id", ""))), f"id must be UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be integer >= 1, got {data.get('version')!r}"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 — append-only entities carry only id + created_at."""
    assert is_valid_uuid(str(data.get("id", ""))), \
        f"id must be UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert "updated_at" not in data, \
        "append-only entity must not expose updated_at (PRD §2.4)"
    assert "version" not in data, \
        "append-only entity must not expose version (PRD §2.4)"


# ---------------------------------------------------------------------------
# Elder
# ---------------------------------------------------------------------------
def assert_elder(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in {
        "PENDING_ADMISSION", "ADMITTED", "ON_LEAVE", "DISCHARGED",
    }, f"unexpected elder.status: {data['status']!r}"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["id_card_number"], str)
    assert isinstance(data["deposit_balance_cents"], int)
    assert data["deposit_balance_cents"] >= 0, \
        "PRD §3.7: deposit_balance_cents never goes below zero"
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, \
        "outstanding_balance_cents is a non-negative aggregate"


# ---------------------------------------------------------------------------
# Room / Bed
# ---------------------------------------------------------------------------
def assert_room(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["room_type"] in {"STANDARD", "INTENSIVE_CARE"}
    assert isinstance(data["floor"], int) and data["floor"] >= 1


def assert_bed(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in {"AVAILABLE", "OCCUPIED", "MAINTENANCE"}, \
        f"unexpected bed.status: {data['status']!r}"
    assert data["bed_type"] in {"SINGLE", "DOUBLE", "MULTI", "INTENSIVE_CARE"}
    assert isinstance(data["monthly_bed_fee_cents"], int)
    assert data["monthly_bed_fee_cents"] >= 0


# ---------------------------------------------------------------------------
# Waitlist (append-only)
# ---------------------------------------------------------------------------
def assert_waitlist_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["status"] in {"QUEUED", "OFFERED", "FULFILLED", "CANCELLED"}
    assert isinstance(data["priority_score"], int)
    assert data["requested_bed_type"] in \
        {"SINGLE", "DOUBLE", "MULTI", "INTENSIVE_CARE"}


# ---------------------------------------------------------------------------
# Care Assessment
# ---------------------------------------------------------------------------
def assert_care_assessment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in {
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED",
    }
    assert 0 <= data["adl_score"] <= 100
    assert 0 <= data["cognitive_score"] <= 30
    assert 0 <= data["medical_condition_score"] <= 50
    if data["status"] != "DRAFT":
        # PRD §3.2 — composite + classification are present after submit
        assert isinstance(data.get("composite_score"), (int, float)), \
            "composite_score must exist after submit"
        if data.get("classification") is not None:
            assert data["classification"] in {"L1", "L2", "L3", "L4", "INTENSIVE"}


# ---------------------------------------------------------------------------
# Care Plan
# ---------------------------------------------------------------------------
def assert_care_plan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in {
        "DRAFT", "ACTIVE", "UNDER_REVIEW", "SUPERSEDED", "ARCHIVED",
    }
    assert isinstance(data["daily_tasks"], list)


# CareTaskExecution: append-only
def assert_care_task_execution(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["task_type"] in {
        "BATHING", "FEEDING", "TURNING", "MEDICATION", "VITALS",
    }
    assert data["outcome"] in {"COMPLETED", "REFUSED", "OMITTED"}


# ---------------------------------------------------------------------------
# Prescription
# ---------------------------------------------------------------------------
def assert_prescription(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in {
        "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "DISCONTINUED",
    }
    assert isinstance(data["drug_code"], str) and data["drug_code"]
    assert isinstance(data["frequency_per_day"], int) and data["frequency_per_day"] >= 1
    assert isinstance(data["is_controlled_substance"], bool)


# MedicationAdministration: append-only
def assert_medication_administration(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["outcome"] in {"ADMINISTERED", "REFUSED", "OMITTED", "ERROR"}


def assert_medication_error_report(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["error_type"] in {
        "WRONG_DRUG", "WRONG_DOSE", "WRONG_TIME", "INTERACTION", "OTHER",
    }
    assert data["severity"] in {"MINOR", "MODERATE", "SEVERE"}


# ---------------------------------------------------------------------------
# Visit Reservation
# ---------------------------------------------------------------------------
def assert_visit_reservation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in {
        "RESERVED", "CHECKED_IN", "COMPLETED", "CANCELLED", "DENIED",
    }


# ---------------------------------------------------------------------------
# Bill
# ---------------------------------------------------------------------------
def assert_bill(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["status"] in {
        "DRAFT", "FINALIZED", "PAID", "REFUNDED", "ADJUSTED",
    }
    assert data["billing_mode"] in {"PACKAGE", "A_LA_CARTE"}


def assert_bill_finalized_invariants(data: Dict[str, Any]) -> None:
    """PRD §3.7: subtotal = sum of line items; subsidy floored, never above
    monthly cap; amount_due never below zero."""
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["government_subsidy_cents"], int)
    assert data["government_subsidy_cents"] >= 0
    assert data["government_subsidy_cents"] <= 200_000, \
        "PRD §3.7: subsidy capped at 2,000.00 (200,000 cents)"
    assert isinstance(data["insurance_offset_cents"], int)
    assert data["insurance_offset_cents"] >= 0
    assert isinstance(data["deposit_applied_cents"], int)
    assert data["deposit_applied_cents"] >= 0
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0, "PRD §3.7: amount_due never negative"
    li_sum = sum(int(li.get("amount_cents", 0)) for li in data.get("line_items", []))
    assert li_sum == data["subtotal_cents"], \
        f"subtotal_cents must equal sum(line_items.amount_cents), got " \
        f"{li_sum} vs {data['subtotal_cents']}"


# ---------------------------------------------------------------------------
# Epidemic / Audit / External event
# ---------------------------------------------------------------------------
def assert_epidemic_config(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert data["mode"] in {"NORMAL", "RESTRICTED", "LOCKDOWN"}
    assert isinstance(data["max_visitors_per_day"], int)


def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["entity_type"] in {
        "CarePlan", "Prescription", "MedicationAdministration",
        "CareAssessment",
    }, f"PRD §2.8: only four audited domains: {data['entity_type']!r}"
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert is_iso8601_timestamp(str(data.get("occurred_at", ""))), \
        f"occurred_at must be ISO 8601: {data.get('occurred_at')!r}"


def assert_external_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["source"] in {"PAYMENT", "IM", "HOSPITAL", "GOVT_SUBSIDY"}
    assert data["result_status"] in {"APPLIED", "DUPLICATE", "REJECTED"}


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------
def find_audit_logs(rows: Iterable[Dict[str, Any]],
                    entity_type: Optional[str] = None,
                    entity_id: Optional[str] = None,
                    action: Optional[str] = None) -> list:
    out = []
    for row in rows:
        if entity_type is not None and row.get("entity_type") != entity_type:
            continue
        if entity_id is not None and row.get("entity_id") != entity_id:
            continue
        if action is not None and row.get("action") != action:
            continue
        out.append(row)
    return out


__all__ = [
    "assert_elder", "assert_room", "assert_bed", "assert_waitlist_entry",
    "assert_care_assessment", "assert_care_plan",
    "assert_care_task_execution", "assert_prescription",
    "assert_medication_administration", "assert_medication_error_report",
    "assert_visit_reservation", "assert_bill",
    "assert_bill_finalized_invariants", "assert_epidemic_config",
    "assert_audit_log", "assert_external_event",
    "find_audit_logs",
]
