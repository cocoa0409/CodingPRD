"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validates the shape the PRD promises. Append-only
records (MIBCheck, PremiumPayment, CashValueEntry) are checked to carry id +
created_at and NOT to carry version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

APPLICATION_STATES = {
    "DRAFT", "SUBMITTED", "EXAM_PENDING", "UNDER_REVIEW", "APPROVED_OFFER",
    "POSTPONED", "DECLINED", "ISSUED", "EXPIRED",
}
EXAM_STATES = {"ORDERED", "COMPLETED", "CANCELLED"}
RISK_CLASSES = {
    "PREFERRED", "STANDARD",
    "TABLE_1", "TABLE_2", "TABLE_3", "TABLE_4",
    "TABLE_5", "TABLE_6", "TABLE_7", "TABLE_8",
}
LIFECYCLE_STATES = {"IN_FORCE", "GRACE", "LAPSED", "REINSTATED", "TERMINATED"}
CONTESTABILITY_STATES = {"CONTESTABLE", "INCONTESTABLE"}


def _assert_common(data: dict):
    """id + created_at + updated_at + version (versioned entities)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only(data: dict):
    """id + created_at only; no version, no updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["base_annual_rate_per_thousand_cents"], int)
    assert isinstance(data["max_face_amount_cents"], int)
    assert isinstance(data["cash_value_accrual_rate_bps"], int)
    assert isinstance(data["contestability_months"], int)
    assert isinstance(data["grace_period_days"], int)
    assert isinstance(data["max_loan_to_cash_value_pct"], int)
    assert isinstance(data["exam_validity_days"], int)


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["sex"] in {"MALE", "FEMALE"}
    assert isinstance(data["tobacco_use"], bool)
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_underwriter(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["license_id"], str) and len(data["license_id"]) > 0


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["requested_face_amount_cents"], int)
    assert data["status"] in APPLICATION_STATES, f"unexpected status {data['status']!r}"


def assert_paramed_exam(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["height_inches"], int)
    assert isinstance(data["weight_pounds"], int)
    assert isinstance(data["systolic_bp"], int)
    assert isinstance(data["exam_date"], str)
    assert data["status"] in EXAM_STATES, f"unexpected exam status {data['status']!r}"


def assert_risk_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["build_debits"], int)
    assert isinstance(data["total_debits"], int)
    assert data["risk_class"] in RISK_CLASSES, f"unexpected risk_class {data['risk_class']!r}"
    assert isinstance(data["table_rating"], int)
    assert isinstance(data["finalized"], bool)


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["face_amount_cents"], int)
    assert isinstance(data["annual_premium_cents"], int)
    assert isinstance(data["issue_date"], str)
    assert data["lifecycle_status"] in LIFECYCLE_STATES, f"unexpected lifecycle_status {data['lifecycle_status']!r}"
    assert data["contestability_status"] in CONTESTABILITY_STATES, f"unexpected contestability_status {data['contestability_status']!r}"
    assert isinstance(data["next_premium_due_date"], str)
    assert isinstance(data["cumulative_premium_paid_cents"], int)
    assert isinstance(data["gross_cash_value_cents"], int)
    assert isinstance(data["outstanding_loan_principal_cents"], int)
    assert isinstance(data["net_cash_value_cents"], int)


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["designation"] in {"PRIMARY", "CONTINGENT"}
    assert isinstance(data["share_pct"], int)


def assert_policy_loan(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["principal_cents"], int)
    assert data["status"] in {"ACTIVE", "REPAID"}


def assert_mib_check(data: dict):
    _assert_append_only(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["mib_hit"], bool)
    assert isinstance(data["rx_flag_count"], int)
    assert data["result"] in {"CLEAR", "FLAGGED"}


def assert_premium_payment(data: dict):
    _assert_append_only(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["amount_cents"], int)


def assert_cash_value_entry(data: dict):
    _assert_append_only(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] in {"PREMIUM_ACCRUAL", "LOAN_REVERSAL", "LAPSE_FORFEIT"}


def assert_net_cash_value_floor(policy: dict):
    """net = max(0, gross - outstanding); never below zero (PRD §2.8)."""
    gross = policy["gross_cash_value_cents"]
    outstanding = policy["outstanding_loan_principal_cents"]
    expected_net = max(0, gross - outstanding)
    assert policy["net_cash_value_cents"] == expected_net, (
        f"net_cash_value_cents should be max(0, {gross} - {outstanding}) = {expected_net}, "
        f"got {policy['net_cash_value_cents']}"
    )
    assert policy["net_cash_value_cents"] >= 0, "net_cash_value_cents must never be negative"
