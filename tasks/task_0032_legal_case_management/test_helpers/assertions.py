"""Per-entity assertion helpers — validate response structure against PRD.

These helpers cover the minimum invariants every successful response of a
given entity must satisfy. Tests still assert the specific business
values they care about; ``assert_<entity>`` exists so every test path
that returns an entity also confirms shape.

PRD §2.4 distinguishes entities with common audit fields from append-only
logs (CustodyEvent, EvidenceRebuttal, AuditLog). The latter carry only
``id`` and ``created_at`` — their assertions intentionally do NOT demand
``updated_at`` or ``version``.
"""
from __future__ import annotations
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------
def _assert_common_id(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 with three fractional digits, "
        f"got {data.get('created_at')!r}"
    )


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """For entities that PRD §2.4 marks as carrying common audit fields."""
    _assert_common_id(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int, got {type(data.get('version')).__name__}"
    )
    assert data["version"] >= 1, "version starts at 1 (PRD §2.4)"


# ---------------------------------------------------------------------------
# Entities with common fields
# ---------------------------------------------------------------------------
def assert_lawyer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["bar_number"], str) and data["bar_number"]
    assert data["role"] in {"JUNIOR", "SENIOR", "PARTNER"}
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["hourly_rate_cents"] >= 0
    assert data["status"] in {"ACTIVE", "SUSPENDED"}
    assert isinstance(data.get("client_history", []), list)


def assert_case(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert data["case_type"] in {
        "CIVIL", "CRIMINAL", "ADMINISTRATIVE", "ARBITRATION"
    }
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["claim_amount_cents"], int)
    assert data["claim_amount_cents"] >= 0
    assert is_valid_uuid(data["lead_lawyer_id"])
    assert data["status"] in {
        "INTAKE", "ACTIVE", "ON_HOLD", "AWAITING_SETTLEMENT",
        "CLOSED", "ARCHIVED",
    }
    assert data["posture"] in {"OPEN", "RESTRICTED", "FROZEN"}
    assert isinstance(data["client_identity_hash"], str)
    assert isinstance(data["opposing_identity_hash"], str)
    assert isinstance(data["intake_document_id"], str)


def assert_party(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["party_role"] in {
        "PLAINTIFF", "DEFENDANT", "THIRD_PARTY", "WITNESS"
    }
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["id_document_number"], str)
    assert isinstance(data["identity_verified"], bool)
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["contact_phone"], str)
    assert data["access_level"] in {"STANDARD", "RESTRICTED", "NONE"}


def assert_template(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["template_code"], str) and data["template_code"]
    assert data["case_type"] in {
        "CIVIL", "CRIMINAL", "ADMINISTRATIVE", "ARBITRATION"
    }
    assert isinstance(data["name"], str)
    assert isinstance(data["variables"], list)
    assert isinstance(data["body_template"], str)
    assert data["status"] in {"ACTIVE", "RETIRED"}


def assert_document_draft(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["template_id"])
    assert isinstance(data["template_version_pinned"], int)
    assert data["template_version_pinned"] >= 1
    assert isinstance(data["version_number"], int)
    assert data["version_number"] >= 1
    assert isinstance(data["rendered_body"], str)
    assert is_valid_uuid(data["drafter_lawyer_id"])
    assert data["status"] in {
        "DRAFTING", "IN_REVIEW", "REVISING",
        "SIGNED_OFF", "LOCKED", "RETIRED",
    }


def assert_hearing(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["court_room"], str) and data["court_room"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert is_valid_uuid(data["lead_lawyer_id"])
    assert data["status"] in {
        "SCHEDULED", "RESCHEDULED", "COMPLETED", "CANCELLED"
    }
    assert isinstance(data["prep_tasks_generated"], bool)


def assert_evidence(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["evidence_type"] in {
        "DOCUMENTARY", "PHYSICAL", "DIGITAL", "TESTIMONIAL"
    }
    assert is_iso8601_timestamp(data["collected_at"])
    assert is_valid_uuid(data["collected_by_lawyer_id"])
    assert data["status"] in {
        "COLLECTED", "SUBMITTED", "REBUTTED", "EXCLUDED"
    }
    assert isinstance(data["rebuttal_count"], int)
    assert data["rebuttal_count"] >= 0


def assert_time_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["lawyer_id"])
    assert isinstance(data["minutes"], int)
    assert isinstance(data["billable"], bool)
    assert isinstance(data["hourly_rate_cents_pinned"], int)
    assert data["hourly_rate_cents_pinned"] >= 0
    assert data["status"] in {"LOGGED", "ADJUSTED", "WRITTEN_OFF", "BILLED"}
    assert isinstance(data["adjustment_minutes"], int)


def assert_bill(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["case_id"])
    assert data["billing_mode"] in {"HOURLY", "FIXED", "CONTINGENT"}
    assert data["status"] in {
        "DRAFT", "ISSUED", "PAID", "SETTLED", "VOIDED"
    }


# ---------------------------------------------------------------------------
# Append-only logs (PRD §2.4: only id + created_at, no updated_at/version)
# ---------------------------------------------------------------------------
def assert_custody_event(data: Dict[str, Any]) -> None:
    _assert_common_id(data)
    assert is_valid_uuid(data["evidence_id"])
    assert is_valid_uuid(data["actor_lawyer_id"])
    assert data["action"] in {
        "COLLECTED", "TRANSFERRED", "EXAMINED", "SUBMITTED", "RETURNED"
    }
    assert is_iso8601_timestamp(data["occurred_at"])
    # PRD §2.4: append-only logs do NOT carry updated_at/version


def assert_rebuttal(data: Dict[str, Any]) -> None:
    _assert_common_id(data)
    assert is_valid_uuid(data["evidence_id"])
    assert is_valid_uuid(data["filed_by_lawyer_id"])
    assert isinstance(data["ground"], str) and data["ground"]
    assert data["status"] in {"OPEN", "UPHELD", "DISMISSED"}


def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_common_id(data)
    assert data["subject_type"] in {
        "DOCUMENT_DRAFT", "EVIDENCE", "CUSTODY_EVENT"
    }
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["action"], str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_bill_total_due_invariants(data: Dict[str, Any]) -> None:
    """PRD §3.6: 'if the result would be negative, it is clamped to zero.'

    PRD §3.6 also fixes the evaluation order: court_fee + attorney_fee +
    expense_reimbursement_cents - cost_recovery_cents, then clamp.
    """
    assert data["total_due_cents"] >= 0
    assert data["court_fee_cents"] >= 0
    assert data["attorney_fee_cents"] >= 0
    assert data["expense_reimbursement_cents"] >= 0
    assert data["cost_recovery_cents"] >= 0


__all__ = [
    "assert_lawyer",
    "assert_case",
    "assert_party",
    "assert_template",
    "assert_document_draft",
    "assert_hearing",
    "assert_evidence",
    "assert_time_entry",
    "assert_bill",
    "assert_custody_event",
    "assert_rebuttal",
    "assert_audit_log_entry",
    "assert_bill_total_due_invariants",
]
