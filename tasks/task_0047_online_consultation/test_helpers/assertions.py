"""Per-entity assertions for the Online Consultation API.

Each `assert_<entity>(data)` helper checks the structural fields PRD §2.4
and §3 declare on that entity. They serve as the structural invariant
check that callers run after every successful mutation.

PRD §2.4: 'All primary resources except DepartmentMapping and AuditLog
expose the same four system-managed fields' (id, created_at, updated_at,
version). Those two exceptions carry only id + created_at.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _check_common_fields(data: Dict[str, Any], entity_name: str) -> None:
    """Common fields per PRD §2.4: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity_name} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}.created_at must be ISO 8601 UTC, "
        f"got {data.get('created_at')!r}"
    )
    assert "updated_at" in data and is_iso8601_timestamp(data["updated_at"]), (
        f"{entity_name}.updated_at must be ISO 8601 UTC, "
        f"got {data.get('updated_at')!r}"
    )
    assert "version" in data, f"{entity_name} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity_name}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any],
                              entity_name: str) -> None:
    """PRD §2.4: DepartmentMapping and AuditLog carry only id + created_at;
    they do NOT carry updated_at or version."""
    assert "id" in data, f"{entity_name} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}.created_at must be ISO 8601 UTC"
    )


# ---------------------------------------------------------------------------
# Patient (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Patient")
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("region_code"), str)
    # PRD §3.1: insurance_status starts at UNKNOWN.
    assert data.get("insurance_status") in {
        "UNKNOWN", "ELIGIBLE", "INELIGIBLE", "SUSPENDED",
    }
    assert isinstance(data.get("chronic_condition_codes", []), list)


# ---------------------------------------------------------------------------
# Doctor (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_doctor(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Doctor")
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("department_code"), str)
    assert isinstance(data.get("specialty_codes"), list)
    assert isinstance(data.get("licensed_region_codes"), list)
    assert data.get("status") in {
        "AVAILABLE", "BUSY", "OFF_DUTY", "SUSPENDED",
    }
    assert isinstance(data.get("max_concurrent_sessions"), int)
    assert data["max_concurrent_sessions"] >= 1


# ---------------------------------------------------------------------------
# Pharmacist (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_pharmacist(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Pharmacist")
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("license_number"), str)
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# DepartmentMapping (PRD §2.4: append-only — no updated_at/version)
# ---------------------------------------------------------------------------
def assert_department_mapping(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "DepartmentMapping")
    assert isinstance(data.get("department_code"), str)
    assert isinstance(data.get("disease_codes"), list)
    assert isinstance(data.get("triage_priority"), int)


# ---------------------------------------------------------------------------
# TriageSession (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_triage_session(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "TriageSession")
    assert data.get("status") in {
        "COLLECTING", "ASSESSED", "EMERGENCY_ROUTED", "MATCHED", "CLOSED",
    }
    assert isinstance(data.get("questionnaire_responses"), list)
    if data.get("status") in {"ASSESSED", "EMERGENCY_ROUTED",
                              "MATCHED", "CLOSED"}:
        # PRD §3.2: scores are persisted at assess.
        assert isinstance(data.get("severity_score"), int)
        assert data.get("severity_band") in {
            "LOW", "MID", "HIGH", "EMERGENCY",
        }


# ---------------------------------------------------------------------------
# Consultation (PRD §3.3–§3.5)
# ---------------------------------------------------------------------------
def assert_consultation(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Consultation")
    assert data.get("mode") in {"REAL_TIME", "APPOINTMENT"}
    assert data.get("media_type") in {"TEXT_IMAGE", "VIDEO"}
    assert data.get("session_status") in {
        "PENDING", "QUEUED", "ACCEPTED", "IN_PROGRESS",
        "COMPLETED", "TRANSFERRED", "CANCELLED",
    }
    assert data.get("quality_status") in {
        "NOT_APPLICABLE", "OK", "DEGRADED", "FAILED",
    }
    assert isinstance(data.get("image_attachment_ids", []), list)


# ---------------------------------------------------------------------------
# Prescription (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_prescription(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "Prescription")
    assert data.get("status") in {
        "DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED",
        "DISPATCHED", "DISPENSED", "FAILED",
    }
    assert data.get("eligibility_flag") in {"ELIGIBLE", "INELIGIBLE"}
    assert data.get("dispatch_target_kind") in {"PHARMACY", "ECOMMERCE"}
    assert data.get("dispensing_status") in {
        "NONE", "RECEIVED", "PREPARING", "READY", "DELIVERED", "FAILED",
    }
    assert isinstance(data.get("items"), list)
    assert isinstance(data.get("gross_amount_cents"), int)
    assert isinstance(data.get("revision_count"), int)


# ---------------------------------------------------------------------------
# InsuranceClaim (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_insurance_claim(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "InsuranceClaim")
    assert data.get("status") in {
        "ELIGIBILITY_PENDING", "VERIFIED", "INELIGIBLE",
        "SETTLING", "SETTLED", "REJECTED_BY_BUREAU",
    }
    assert isinstance(data.get("claim_amount_cents"), int)
    assert isinstance(data.get("reimbursed_cents"), int)
    assert isinstance(data.get("self_pay_cents"), int)


def assert_settlement_invariant(claim: Dict[str, Any]) -> None:
    """PRD §3.7: 'the audit point at which the compensating invariant
    claim_amount_cents == reimbursed_cents + self_pay_cents must hold.'"""
    expected = claim["claim_amount_cents"]
    actual = claim["reimbursed_cents"] + claim["self_pay_cents"]
    assert actual == expected, (
        "Compensating invariant violated: "
        f"reimbursed_cents ({claim['reimbursed_cents']}) "
        f"+ self_pay_cents ({claim['self_pay_cents']}) "
        f"= {actual}, expected claim_amount_cents={expected}"
    )


# ---------------------------------------------------------------------------
# FollowUpTask (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_follow_up_task(data: Dict[str, Any]) -> None:
    _check_common_fields(data, "FollowUpTask")
    assert data.get("status") in {
        "PLANNED", "REMINDED", "SUBMITTED", "ESCALATED", "CLOSED",
    }
    assert isinstance(data.get("reminder_channels"), list)
    assert isinstance(data.get("abnormal_flag"), bool)


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.4: append-only — no updated_at/version)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditLog")
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_user_id"), str)
    assert isinstance(data.get("action_code"), str)
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)


# ---------------------------------------------------------------------------
# Helpers for searching audit logs
# ---------------------------------------------------------------------------
def find_audit_entries(
    rows: Iterable[Dict[str, Any]],
    *,
    action_code: Optional[str] = None,
    target_id: Optional[str] = None,
    target_entity: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        if action_code is not None and r.get("action_code") != action_code:
            continue
        if target_id is not None and r.get("target_id") != target_id:
            continue
        if target_entity is not None and r.get("target_entity") != target_entity:
            continue
        out.append(r)
    return out


__all__ = [
    "assert_patient",
    "assert_doctor",
    "assert_pharmacist",
    "assert_department_mapping",
    "assert_triage_session",
    "assert_consultation",
    "assert_prescription",
    "assert_insurance_claim",
    "assert_settlement_invariant",
    "assert_follow_up_task",
    "assert_audit_log",
    "find_audit_entries",
]
