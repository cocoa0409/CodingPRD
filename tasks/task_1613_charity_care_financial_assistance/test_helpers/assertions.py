"""Entity assertions and domain invariant checkers (PRD §2.5, §2.12)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Common server-managed properties (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_light(data: dict):
    """Append-only resources carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "light resource must not carry updated_at (PRD §2.5)"
    assert "version" not in data, "light resource must not carry version (PRD §2.5)"


def assert_decimal_eq(actual, expected, label="value"):
    """Percentages/scores are decimal numbers with pinned precision (PRD §2.6)."""
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(float(expected), abs=1e-6), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_eq(actual, expected_iso, label="timestamp"):
    """Compare two ISO 8601 instants for equality, tolerating an optional
    fractional-second rendering of the same instant."""
    def _parse(v):
        assert isinstance(v, str), f"{label} must be a string, got {v!r}"
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)

    assert _parse(actual) == _parse(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_financial_assistance_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_code"], str) and data["policy_code"]
    for field in (
        "fpl_base_cents", "fpl_increment_cents", "asset_limit_cents",
        "retroactive_window_days", "notification_period_days", "eca_notice_days",
        "doc_response_days",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents/days"
    for field in ("full_discount_max_fpl_pct", "partial_discount_max_fpl_pct"):
        assert isinstance(data[field], int), f"{field} must be an integer percentage"
    for field in (
        "partial_discount_floor_pct", "presumptive_partial_score_threshold",
        "presumptive_full_score_threshold",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED"]


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["mrn"], str) and data["mrn"]


def assert_patient_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert isinstance(data["encounter_date"], str)
    assert isinstance(data["total_charges_cents"], int) and data["total_charges_cents"] > 0
    assert isinstance(data["insurance_paid_cents"], int) and data["insurance_paid_cents"] >= 0
    for field in (
        "patient_responsibility_cents", "adjusted_balance_cents",
        "effective_payments_cents", "amount_outstanding_cents", "overpayment_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be non-negative integer cents"
        )
    assert data.get("first_statement_at") is None or is_iso8601_timestamp(
        data["first_statement_at"]
    )
    assert data["collection_posture"] in [
        "NOT_IN_COLLECTIONS", "NOTICE_PERIOD", "ECA_ELIGIBLE", "ECA_ACTIVE",
        "ASSISTANCE_HOLD", "RESOLVED",
    ]


def assert_ledger_invariants(account: dict):
    """Derived ledger chain (PRD §2.12): outstanding and overpayment are the
    floored differences between adjusted balance and effective payments, and an
    account whose outstanding is zero holds posture RESOLVED."""
    assert account["amount_outstanding_cents"] == max(
        0, account["adjusted_balance_cents"] - account["effective_payments_cents"]
    ), (
        f"amount_outstanding mismatch: {account['amount_outstanding_cents']} vs "
        f"adjusted {account['adjusted_balance_cents']} / effective "
        f"{account['effective_payments_cents']}"
    )
    assert account["overpayment_cents"] == max(
        0, account["effective_payments_cents"] - account["adjusted_balance_cents"]
    )
    if account["amount_outstanding_cents"] == 0:
        assert account["collection_posture"] == "RESOLVED", (
            "zero outstanding must hold posture RESOLVED (PRD §2.12)"
        )


def assert_account_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["paid_at"], str)
    assert data["method"] in ["CARD", "CHECK", "ACH", "CASH"]
    assert isinstance(data["refunded_cents"], int) and 0 <= data["refunded_cents"] <= data["amount_cents"]
    assert data["status"] in ["POSTED", "PARTIALLY_REFUNDED", "FULLY_REFUNDED"]


def assert_assistance_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be a UUID"
    assert data["screening_source"] in ["STANDARD", "PRESUMPTIVE"]
    assert isinstance(data["reported_annual_income_cents"], int)
    assert isinstance(data["reported_liquid_assets_cents"], int)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 0
    assert isinstance(data["annualized_verified_income_cents"], int)
    assert isinstance(data["verified_liquid_assets_cents"], int)
    assert isinstance(data["requested_doc_types"], list)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "PENDING_DOCUMENTS",
        "APPROVED", "DENIED", "EXPIRED", "WITHDRAWN",
    ]


def assert_household_member(data: dict):
    _assert_light(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["relationship"] in ["SELF", "SPOUSE", "CHILD", "OTHER_DEPENDENT"]
    assert isinstance(data["age"], int) and 0 <= data["age"] <= 130


def assert_verification_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data["doc_type"] in ["PAY_STUB", "TAX_RETURN", "BENEFIT_LETTER", "BANK_STATEMENT", "IDENTITY"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["SUBMITTED", "VERIFIED", "REJECTED"]


def assert_presumptive_screening(data: dict):
    _assert_light(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    for field in (
        "income_band_score", "payment_history_score", "utilization_score",
        "public_benefit_score", "housing_stability_score",
    ):
        assert data.get(field) is None or (isinstance(data[field], int) and 0 <= data[field] <= 100)
    assert isinstance(data["present_factor_count"], int) and 0 <= data["present_factor_count"] <= 5
    assert isinstance(data["thin_file"], bool)
    assert isinstance(data["propensity_score"], (int, float))
    assert data["outcome"] in ["ELIGIBLE_FULL", "ELIGIBLE_PARTIAL", "NOT_ELIGIBLE"]


def assert_discount_determination(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data["basis"] in ["VERIFIED_APPLICATION", "PRESUMPTIVE_SCORE"]
    assert isinstance(data["covered_account_ids"], list)
    assert is_valid_uuid(data.get("policy_id", "")), "policy_id must be a UUID"
    assert isinstance(data["policy_version"], int)
    assert data.get("fpl_pct_snapshot") is None or isinstance(
        data["fpl_pct_snapshot"], (int, float)
    )
    assert data["tier"] in ["TIER_FULL", "TIER_PARTIAL", "INELIGIBLE"]
    assert isinstance(data["discount_pct"], (int, float))
    assert data["status"] in ["PRELIMINARY", "FINAL", "REVERSED"]


def assert_account_adjustment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("determination_id", "")), "determination_id must be a UUID"
    assert data["adjustment_type"] in ["WRITE_OFF", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data.get("payment_id") is None or isinstance(data["payment_id"], str)
    assert data["status"] in ["POSTED", "REVERSED"]


def assert_notification_record(data: dict):
    _assert_light(data)
    assert data["notice_type"] in [
        "FIRST_STATEMENT", "PLAIN_LANGUAGE_SUMMARY", "ECA_WARNING",
        "DETERMINATION_LETTER", "DOC_REQUEST",
    ]
    assert data.get("delivery_channel") in [None, "MAIL", "PORTAL", "EMAIL"]
    assert isinstance(data["is_plain_language"], bool)
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601 UTC"


def assert_collection_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["action_type"] in [
        "CREDIT_REPORT", "LAWSUIT", "WAGE_GARNISHMENT", "LIEN", "SALE_TO_AGENCY"
    ]
    assert data["status"] in ["INITIATED", "HALTED", "COMPLETED"]


def assert_community_benefit_report(data: dict):
    _assert_common(data)
    assert isinstance(data["reporting_year"], int)
    for field in (
        "total_write_offs_cents", "total_standard_write_offs_cents",
        "total_presumptive_write_offs_cents", "total_refunds_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be non-negative integer cents"
        )
    assert isinstance(data["accounts_assisted_count"], int) and data["accounts_assisted_count"] >= 0
    assert isinstance(data["totals_stale"], bool)
    assert data["status"] in ["OPEN", "FILED", "REOPENED"]
