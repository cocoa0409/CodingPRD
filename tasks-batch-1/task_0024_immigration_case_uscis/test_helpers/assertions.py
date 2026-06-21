"""Entity assertion helpers — one per primary entity, plus domain invariants.

All assertions verify only what PRD §2.4 / §3.x explicitly guarantees about each
entity's response shape; they tolerate additional fields the implementer may add.
"""
import re

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)
from .constants import RECEIPT_NUMBER_PATTERN, ALIEN_NUMBER_PATTERN


_RECEIPT_RE = re.compile(RECEIPT_NUMBER_PATTERN)
_ALIEN_RE = re.compile(ALIEN_NUMBER_PATTERN)


# ─── Common-fields entities (id + created_at + updated_at + version) ────


def _assert_common_fields(data: dict, entity_name: str = "entity") -> None:
    """PRD §2.4: every primary entity carries id (UUID), created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict, entity_name: str = "entity") -> None:
    """PRD §2.4: append-only rows carry id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )


# ─── Applicant ──────────────────────────────────────────────────


def assert_applicant(data: dict) -> None:
    """Validate Applicant response shape (PRD §3.1)."""
    _assert_common_fields(data, "Applicant")
    assert _ALIEN_RE.match(data["alien_number"]), (
        f"alien_number must match {ALIEN_NUMBER_PATTERN}, got {data['alien_number']!r}"
    )
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["country_of_chargeability"] in {
        "WORLDWIDE", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"
    }, f"country_of_chargeability must be a recognized bucket, got {data['country_of_chargeability']!r}"
    assert isinstance(data["email"], str) and "@" in data["email"]


# ─── Attorney ───────────────────────────────────────────────────


def assert_attorney(data: dict) -> None:
    """Validate Attorney response shape (PRD §3.1)."""
    _assert_common_fields(data, "Attorney")
    assert isinstance(data["bar_number"], str) and data["bar_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["firm_name"], str) and data["firm_name"]


# ─── Case ───────────────────────────────────────────────────────


_CASE_STATUSES = {
    "DRAFT", "FILED", "BIOMETRICS_SCHEDULED", "BIOMETRICS_COMPLETED",
    "UNDER_REVIEW", "RFE_PENDING", "INTERVIEW_SCHEDULED", "INTERVIEW_COMPLETED",
    "APPROVED", "DENIED", "ABANDONED",
}

_CASE_TYPES = {"I-130", "I-485", "I-765", "I-131"}


def assert_case(data: dict) -> None:
    """Validate Case response shape (PRD §3.1)."""
    _assert_common_fields(data, "Case")
    assert is_valid_uuid(data["applicant_id"]), "Case.applicant_id must be a UUID"
    assert data["case_type"] in _CASE_TYPES, (
        f"Case.case_type must be one of {_CASE_TYPES}, got {data['case_type']!r}"
    )
    assert data["status"] in _CASE_STATUSES, (
        f"Case.status must be a known status, got {data['status']!r}"
    )
    assert isinstance(data.get("rfe_round_count"), int) and data["rfe_round_count"] >= 0


def assert_filed_case(data: dict) -> None:
    """A FILED (or later) case carries the stamped fields from PRD §3.2."""
    assert_case(data)
    assert _RECEIPT_RE.match(data["receipt_number"]), (
        f"receipt_number must match {RECEIPT_NUMBER_PATTERN}, "
        f"got {data['receipt_number']!r}"
    )
    assert isinstance(data["file_date"], str) and len(data["file_date"]) == 10
    assert isinstance(data["priority_date"], str) and len(data["priority_date"]) == 10
    assert isinstance(data["filing_fee_cents"], int) and data["filing_fee_cents"] >= 0
    assert isinstance(data["assigned_officer_id"], str) and data["assigned_officer_id"]


# ─── BiometricsAppointment ──────────────────────────────────────


_BIO_STATUSES = {"SCHEDULED", "COMPLETED", "NO_SHOW", "RESCHEDULED"}


def assert_biometrics(data: dict) -> None:
    _assert_common_fields(data, "BiometricsAppointment")
    assert is_valid_uuid(data["case_id"]), "BiometricsAppointment.case_id must be a UUID"
    assert isinstance(data["scheduled_at"], str)
    assert isinstance(data["asc_location_code"], str) and data["asc_location_code"]
    assert data["status"] in _BIO_STATUSES


# ─── RFE ────────────────────────────────────────────────────────


_RFE_STATUSES = {"ISSUED", "RESPONDED", "EXPIRED"}


def assert_rfe(data: dict) -> None:
    _assert_common_fields(data, "RFE")
    assert is_valid_uuid(data["case_id"]), "RFE.case_id must be a UUID"
    assert isinstance(data["issued_at"], str) and data["issued_at"]
    assert isinstance(data["response_deadline"], str) and len(data["response_deadline"]) >= 10
    assert isinstance(data["evidence_items_requested"], list)
    assert data["status"] in _RFE_STATUSES


# ─── InterviewAppointment ───────────────────────────────────────


_INTERVIEW_STATUSES = {"SCHEDULED", "COMPLETED", "NO_SHOW", "RESCHEDULED"}
_INTERVIEW_DECISIONS = {"APPROVE", "DENY", "NEEDS_REVIEW"}


def assert_interview(data: dict) -> None:
    _assert_common_fields(data, "InterviewAppointment")
    assert is_valid_uuid(data["case_id"]), "InterviewAppointment.case_id must be a UUID"
    assert isinstance(data["scheduled_at"], str)
    assert isinstance(data["field_office_code"], str) and data["field_office_code"]
    assert data["status"] in _INTERVIEW_STATUSES
    decision = data.get("decision_after_interview")
    assert decision is None or decision in _INTERVIEW_DECISIONS


# ─── Append-only entities ───────────────────────────────────────


def assert_visa_bulletin_entry(data: dict) -> None:
    """VisaBulletinEntry is immutable — id + created_at only, no updated_at/version (PRD §2.4)."""
    _assert_append_only_fields(data, "VisaBulletinEntry")
    assert isinstance(data["bulletin_month"], str) and len(data["bulletin_month"]) == 7
    assert data["preference_category"] in {"F1", "F2A", "F2B", "F3", "F4", "IR"}
    assert data["country"] in {"WORLDWIDE", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"}
    assert data["chart_type"] in {"FINAL_ACTION", "FILING_DATE"}
    assert isinstance(data["cutoff_date"], str) and data["cutoff_date"]


def assert_case_event(data: dict) -> None:
    """CaseEvent is append-only — id + created_at only (PRD §2.4)."""
    _assert_append_only_fields(data, "CaseEvent")
    assert is_valid_uuid(data["case_id"]), "CaseEvent.case_id must be a UUID"
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["occurred_at"], str)


# ─── Workload response ──────────────────────────────────────────


def assert_workload_response(data: dict, officer_id: str) -> None:
    """Officer workload read returns officer_id + workload_score + case_count (PRD §3.8)."""
    assert data["officer_id"] == officer_id, (
        f"officer_id mismatch: expected {officer_id}, got {data.get('officer_id')!r}"
    )
    assert isinstance(data["workload_score"], (int, float))
    assert isinstance(data["case_count"], int) and data["case_count"] >= 0
