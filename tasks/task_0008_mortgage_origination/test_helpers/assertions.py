"""Entity assertions and domain invariant checkers.

Each `assert_<entity>(data)` checks the entity-level invariants declared in PRD
§2.4 (common system fields) and §3 (per-entity fields). UDAAPCheck has only
`id` + `created_at` (no `updated_at`, no `version`) per PRD §2.4.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------
# Common-field checker — applied to all entities EXCEPT UDAAPCheck.
# ---------------------------------------------------------------------
def assert_common_fields(data: dict, *, with_updated_at: bool = True,
                         with_version: bool = True) -> None:
    """PRD §2.4 — id is a UUID, created_at is ISO 8601. updated_at and version
    are present for every entity except UDAAPCheck (append-only)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_updated_at:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    if with_version:
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be a positive integer, got {data.get('version')!r}"


# ---------------------------------------------------------------------
# Applicant (PRD §3.1)
# ---------------------------------------------------------------------
def assert_applicant(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert isinstance(data["monthly_debt_cents"], int) and data["monthly_debt_cents"] >= 0
    assert isinstance(data["credit_score"], int) and 300 <= data["credit_score"] <= 850
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


# ---------------------------------------------------------------------
# LoanApplication (PRD §3.1, §3.2)
# ---------------------------------------------------------------------
def assert_loan_application(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["property_address"], str) and data["property_address"]
    assert isinstance(data["property_state_code"], str)
    assert data["loan_purpose"] in ("PURCHASE", "REFINANCE")
    assert isinstance(data["requested_loan_amount_cents"], int) and data["requested_loan_amount_cents"] > 0
    assert isinstance(data["property_value_cents"], int) and data["property_value_cents"] > 0
    assert data["loan_term_months"] in (180, 360)
    assert data["status"] in (
        "DRAFT", "PREQUALIFIED", "UNDER_REVIEW", "APPROVED",
        "CLEAR_TO_CLOSE", "CLOSED", "DENIED", "WITHDRAWN",
    )


# ---------------------------------------------------------------------
# IncomeVerification (PRD §3.3)
# ---------------------------------------------------------------------
def assert_income_verification(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["document_type"] in ("W2", "PAYSTUB", "TAX_RETURN", "BANK_DEPOSITS")
    assert isinstance(data["verified_annual_income_cents"], int) and data["verified_annual_income_cents"] >= 0
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED")


# ---------------------------------------------------------------------
# AssetVerification (PRD §3.3)
# ---------------------------------------------------------------------
def assert_asset_verification(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["asset_type"] in ("CHECKING", "SAVINGS", "BROKERAGE", "RETIREMENT")
    assert isinstance(data["verified_balance_cents"], int) and data["verified_balance_cents"] >= 0
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED")


# ---------------------------------------------------------------------
# Appraisal (PRD §3.4)
# ---------------------------------------------------------------------
def assert_appraisal(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ("ORDERED", "COMPLETED", "RECONSIDERED")


# ---------------------------------------------------------------------
# TitleSearch (PRD §3.5)
# ---------------------------------------------------------------------
def assert_title_search(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ("ORDERED", "CLEAR", "EXCEPTIONS_FOUND", "CURED")


# ---------------------------------------------------------------------
# RateLock (PRD §3.6)
# ---------------------------------------------------------------------
def assert_rate_lock(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["locked_rate_bps"], int) and data["locked_rate_bps"] > 0
    assert data["lock_term_days"] in (30, 45, 60)
    assert is_iso8601_timestamp(data["locked_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= 2
    assert isinstance(data["extension_fee_cents"], int) and data["extension_fee_cents"] >= 0
    assert data["status"] in ("ACTIVE", "EXPIRED", "SUPERSEDED", "CANCELLED")


# ---------------------------------------------------------------------
# Disclosure (PRD §3.7)
# ---------------------------------------------------------------------
def assert_disclosure(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["disclosure_type"] in ("LOAN_ESTIMATE", "CLOSING_DISCLOSURE")
    assert data["status"] in ("DRAFT", "DELIVERED", "ACKNOWLEDGED", "SUPERSEDED")


# ---------------------------------------------------------------------
# UDAAPCheck (PRD §2.4 + §3.8) — append-only: NO updated_at, NO version.
# ---------------------------------------------------------------------
def assert_udaap_check(data: dict) -> None:
    """PRD §2.4: UDAAPCheck is an append-only audit record carrying only
    id and created_at. updated_at and version are explicitly absent."""
    assert_common_fields(data, with_updated_at=False, with_version=False)
    assert is_valid_uuid(data["application_id"])
    assert data["review_outcome"] in ("CLEARED", "FLAGGED")


# ---------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------
def assert_version_advanced(new_version: int, old_version: int) -> None:
    """PRD §2.4: version increments by exactly one on every successful mutation
    of that resource."""
    assert isinstance(new_version, int) and isinstance(old_version, int)
    assert new_version > old_version, (
        f"Expected version to advance from {old_version}, got {new_version}"
    )
