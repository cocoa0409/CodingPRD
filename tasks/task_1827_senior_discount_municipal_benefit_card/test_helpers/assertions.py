"""Entity assertions and domain invariant checkers.

Each assert_* validates the structural contract for one resource: system fields
from PRD §2.5 plus the entity's own fields from the PRD §3 workflows. Nullable
workflow fields are checked for presence, not value. The PRD does not pin the
initial value of `version`, so these helpers assert only that it is an integer.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_APPLICATION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
                         "APPROVED", "DENIED")
_DOCUMENT_STATUSES = ("SUBMITTED", "VERIFIED", "REJECTED")
_DOCUMENT_TYPES = ("PROOF_OF_AGE", "PROOF_OF_INCOME", "PROOF_OF_RESIDENCY")
_CARDHOLDER_STATUSES = ("ACTIVE", "RECERTIFICATION_DUE", "SUSPENDED",
                        "LAPSED", "REVOKED")
_CARD_STATUSES = ("ACTIVE", "SUSPENDED", "REPLACED", "EXPIRED", "REVOKED")
_CARD_ISSUE_REASONS = ("INITIAL", "REPLACEMENT", "RENEWAL")
_MERCHANT_STATUSES = ("ACTIVE", "TERMINATED")
_OFFER_STATUSES = ("ACTIVE", "RETIRED")
_OFFER_CATEGORIES = ("GROCERY", "PHARMACY", "DINING", "RETAIL", "SERVICES")
_WAIVER_TYPES = ("TRANSIT_FARE", "FACILITY_FEE")
_TRANSACTION_STATUSES = ("POSTED", "FLAGGED", "VOIDED")
_CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "DENIED")


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_benefit_application(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ("INITIAL", "RECERTIFICATION")
    assert isinstance(data["applicant_full_name"], str) and data["applicant_full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["annual_income_cents"], int)
    assert data["annual_income_cents"] >= 0
    assert isinstance(data["residency_address"], str) and data["residency_address"]
    assert data["status"] in _APPLICATION_STATUSES
    for field in ("cardholder_id", "reviewed_by_user_id", "info_request_reason",
                  "denial_reason", "decided_by_user_id"):
        assert field in data, f"missing field {field}"


def assert_verification_document(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["application_id"], str) and data["application_id"]
    assert data["document_type"] in _DOCUMENT_TYPES
    assert isinstance(data["document_reference"], str)
    assert data["status"] in _DOCUMENT_STATUSES
    for field in ("reviewed_by_user_id", "rejection_reason"):
        assert field in data, f"missing field {field}"


def assert_cardholder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["residency_address"], str) and data["residency_address"]
    assert data["status"] in _CARDHOLDER_STATUSES
    assert "pre_suspension_status" in data
    assert isinstance(data["recertification_due_date"], str)
    # Derived figures surfaced on every read (PRD §3.3).
    assert isinstance(data["fraud_flag_count"], int) and data["fraud_flag_count"] >= 0
    assert isinstance(data["ytd_discount_cents"], int) and data["ytd_discount_cents"] >= 0
    assert isinstance(data["ytd_transaction_count"], int) and data["ytd_transaction_count"] >= 0
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0


def assert_benefit_card(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cardholder_id"], str) and data["cardholder_id"]
    # PRD §3.3: a server-generated unique sixteen-digit card_number.
    assert isinstance(data["card_number"], str) and len(data["card_number"]) == 16
    assert data["card_number"].isdigit()
    assert data["issue_reason"] in _CARD_ISSUE_REASONS
    assert data["status"] in _CARD_STATUSES
    assert is_iso8601_timestamp(data.get("issued_at", "")), \
        "issued_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("expires_at", "")), \
        "expires_at must be an ISO 8601 UTC timestamp"
    assert "replaces_card_id" in data


def assert_merchant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert 0 < data["reimbursement_rate_pct"] <= 100
    assert isinstance(data["monthly_reimbursement_cap_cents"], int)
    assert data["monthly_reimbursement_cap_cents"] >= 0
    assert data["status"] in _MERCHANT_STATUSES
    assert isinstance(data["current_month_reimbursed_cents"], int)
    assert data["current_month_reimbursed_cents"] >= 0


def assert_discount_offer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["merchant_id"], str) and data["merchant_id"]
    assert data["category"] in _OFFER_CATEGORIES
    assert 0 < data["discount_pct"] <= 100
    assert isinstance(data["max_discount_cents"], int) and data["max_discount_cents"] > 0
    assert isinstance(data["valid_from"], str) and data["valid_from"]
    assert isinstance(data["valid_until"], str) and data["valid_until"]
    assert data["status"] in _OFFER_STATUSES


def assert_fee_waiver_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cardholder_id"], str) and data["cardholder_id"]
    assert data["waiver_type"] in _WAIVER_TYPES
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]


def assert_usage_transaction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert isinstance(data["merchant_id"], str) and data["merchant_id"]
    assert isinstance(data["cardholder_id"], str) and data["cardholder_id"]
    assert isinstance(data["offer_id"], str) and data["offer_id"]
    assert data["category"] in _OFFER_CATEGORIES
    assert isinstance(data["purchase_amount_cents"], int)
    assert data["purchase_amount_cents"] > 0
    # PRD §3.6: discount_cents is an integer cent figure, frozen at creation.
    assert isinstance(data["discount_cents"], int) and data["discount_cents"] >= 0
    assert data["status"] in _TRANSACTION_STATUSES
    for field in ("flagged_by_user_id", "flag_reason", "voided_by_user_id"):
        assert field in data, f"missing field {field}"


def assert_reimbursement_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["merchant_id"], str) and data["merchant_id"]
    assert isinstance(data["period_month"], str) and data["period_month"]
    assert "program_fund_id" in data
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["provisional_amount_cents"] >= 0
    assert "final_amount_cents" in data
    assert data["status"] in _CLAIM_STATUSES
    assert "denial_reason" in data


def assert_program_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] > 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["available_cents"], int)


def assert_fund_invariant(data: dict):
    """PRD §3.8: allocated_cents always equals available_cents + paid_cents."""
    assert data["allocated_cents"] == data["available_cents"] + data["paid_cents"], (
        f"fund invariant broken: {data['allocated_cents']} != "
        f"{data['available_cents']} + {data['paid_cents']}"
    )
