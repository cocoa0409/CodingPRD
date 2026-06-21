"""Entity assertions and domain invariant checkers.

Per-entity assertions validate the shape PRD §2.4 promises. The Applicant,
Application, OfficeAction, OfficeActionResponse, MaintenanceFee, and
PCTPhaseEntry entities all carry the four common audit fields. FeePayment
is append-only — it MUST NOT carry `updated_at` or `version`.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict, entity_label: str):
    """Audit fields per PRD §2.4: id (UUID), created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_label}.version must be int >= 1, got {data.get('version')!r}"


def _assert_append_only_fields(data: dict, entity_label: str):
    """Append-only entities (PRD §2.4) carry ONLY id + created_at."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, \
        f"{entity_label} is append-only and must NOT carry updated_at"
    assert "version" not in data, \
        f"{entity_label} is append-only and must NOT carry version"


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) >= 2
    assert data.get("entity_size") in ("LARGE", "SMALL", "MICRO")
    assert isinstance(data.get("prior_applications_filed"), int)
    assert data["prior_applications_filed"] >= 0


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert data.get("application_type") in ("UTILITY", "DESIGN", "PROVISIONAL", "PCT_NATIONAL")
    assert data.get("status") in (
        "FILED", "AWAITING_EXAMINATION", "OFFICE_ACTION_OUTSTANDING",
        "RESPONSE_FILED", "ALLOWED", "ISSUED",
        "ABANDONED", "EXPIRED", "CONVERTED",
    )
    assert isinstance(data.get("title"), str) and len(data["title"]) >= 3
    assert isinstance(data.get("claim_count"), int) and data["claim_count"] >= 1
    assert isinstance(data.get("independent_claim_count"), int) \
        and 1 <= data["independent_claim_count"] <= data["claim_count"]
    assert is_iso8601_timestamp(data.get("filing_date", ""))
    assert isinstance(data.get("total_fees_paid_cents"), int) \
        and data["total_fees_paid_cents"] >= 0


def assert_office_action(data: dict):
    _assert_common_fields(data, "OfficeAction")
    assert data.get("action_type") in ("NON_FINAL", "FINAL", "NOTICE_OF_ALLOWANCE")
    assert data.get("status") in ("OUTSTANDING", "RESPONDED", "EXPIRED", "WITHDRAWN")
    assert is_iso8601_timestamp(data.get("issue_date", ""))
    assert is_iso8601_timestamp(data.get("shortened_due_date", ""))
    assert is_iso8601_timestamp(data.get("maximum_due_date", ""))


def assert_office_action_response(data: dict):
    _assert_common_fields(data, "OfficeActionResponse")
    assert data.get("response_status") in ("ACCEPTED", "REJECTED_LATE")
    assert isinstance(data.get("extension_months_requested"), int)
    assert 0 <= data["extension_months_requested"] <= 3
    assert isinstance(data.get("claim_amendment_count"), int)
    assert isinstance(data.get("extension_fee_cents"), int)
    assert data["extension_fee_cents"] >= 0
    assert is_iso8601_timestamp(data.get("response_filed_at", ""))


def assert_maintenance_fee(data: dict):
    _assert_common_fields(data, "MaintenanceFee")
    assert data.get("window_number") in (1, 2, 3)
    assert data.get("fee_status") in ("PENDING", "PAID", "LAPSED")
    assert is_iso8601_timestamp(data.get("window_open_date", ""))
    assert is_iso8601_timestamp(data.get("window_due_date", ""))
    assert is_iso8601_timestamp(data.get("window_grace_date", ""))
    assert isinstance(data.get("base_fee_cents"), int)
    assert data["base_fee_cents"] >= 0


def assert_pct_phase_entry(data: dict):
    _assert_common_fields(data, "PCTPhaseEntry")
    assert data.get("phase_status") == "ENTERED"
    assert is_iso8601_timestamp(data.get("pct_international_filing_date", ""))
    assert is_iso8601_timestamp(data.get("national_phase_due_date", ""))


def assert_fee_payment(data: dict):
    _assert_append_only_fields(data, "FeePayment")
    assert data.get("payment_status") == "POSTED"
    assert data.get("payment_category") in (
        "FILING", "EXCESS_CLAIMS", "EXTENSION", "ISSUE",
        "MAINTENANCE_W1", "MAINTENANCE_W2", "MAINTENANCE_W3",
        "PCT_NATIONAL_PHASE",
    )
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
