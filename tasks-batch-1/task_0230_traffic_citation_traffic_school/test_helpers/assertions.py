"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response structure against the PRD contract.
PointLedgerEntry is an append-and-mask audit record (PRD §2.4): it carries only
id and created_at, never updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["state_code"], str)
    for field in (
        "base_court_fee_cents", "late_penalty_cents", "installment_setup_fee_cents",
        "min_installment_cents", "collections_age_days", "traffic_school_fee_cents",
        "school_eligible_max_points", "school_cooldown_months",
        "point_suspension_threshold", "point_window_months",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_driver(data: dict):
    _assert_common(data)
    assert data["license_status"] in ("VALID", "HELD", "SUSPENDED")
    assert isinstance(data["point_balance"], int)
    assert isinstance(data["fta_warrant_active"], bool)


def assert_citation(data: dict):
    _assert_common(data)
    assert data["financial_status"] in (
        "DRAFT", "ASSESSED", "PARTIALLY_PAID", "PAID", "VOID",
    )
    assert data["adjudication_status"] in (
        "NONE", "CONTESTED", "DISMISSED", "UPHELD",
    )
    assert data["disposition"] in ("OPEN", "CLOSED")
    for field in (
        "base_fine_cents", "assessed_total_cents", "penalty_cents",
        "amount_paid_cents", "balance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer cents value"


def assert_charge(data: dict):
    _assert_common(data)
    assert isinstance(data["base_fine_cents"], int)
    assert data["points"] in (0, 1, 2)


def assert_installment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "ACTIVE", "COMPLETED", "DEFAULTED", "SUPERSEDED", "CANCELLED",
    )
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["installment_cents"], int)
    assert isinstance(data["term_count"], int)


def assert_installment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "PAID", "MISSED")
    assert isinstance(data["sequence_no"], int)
    assert isinstance(data["amount_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("POSTED", "REVERSED")
    assert data["method"] in ("CARD", "CASH", "CHECK")
    assert isinstance(data["amount_cents"], int)


def assert_contest_request(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "HEARING_SET", "CONTINUANCE", "DISMISSED", "UPHELD", "FTA",
    )
    assert isinstance(data["continuance_count"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "COMPLETED", "FAILED")
    assert isinstance(data["eligible_points"], int)
    assert isinstance(data["points_reduced"], int)


def assert_license_hold(data: dict):
    _assert_common(data)
    assert data["hold_type"] in ("FTA_HOLD", "NONPAYMENT_HOLD", "POINT_SUSPENSION")
    assert data["status"] in ("OPEN", "RELEASED")


def assert_collections_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("REFERRED", "RECALLED")
    assert isinstance(data["outstanding_at_referral_cents"], int)
    assert isinstance(data["collections_fee_cents"], int)


def assert_warrant(data: dict):
    _assert_common(data)
    assert data["reason"] in ("FTA_HEARING", "FTA_APPEAR")
    assert data["status"] in ("ACTIVE", "QUASHED")


def assert_point_ledger_entry(data: dict):
    """PointLedgerEntry carries only id + created_at (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PointLedgerEntry must not carry updated_at"
    assert "version" not in data, "PointLedgerEntry must not carry version"
    assert data["state"] in ("ACTIVE", "MASKED")
    assert isinstance(data["points"], int)
