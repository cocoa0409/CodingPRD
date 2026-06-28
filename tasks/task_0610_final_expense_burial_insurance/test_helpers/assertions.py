"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_product_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["benefit_type"] in ("GUARANTEED_ISSUE", "GRADED_BENEFIT", "LEVEL_BENEFIT")
    assert "version" in data, "ProductPlan carries the full common-field quartet"


def assert_applicant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert data["gender"] in ("MALE", "FEMALE")


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REFERRED", "DECLINED", "ISSUED", "WITHDRAWN",
    )


def assert_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["coverage_status"] in (
        "PENDING", "ACTIVE", "LAPSED", "TERMINATED", "SURRENDERED", "RESCINDED",
    )
    assert data["payment_status"] in ("CURRENT", "GRACE", "DELINQUENT")
    assert "version" in data, "Policy carries the full common-field quartet"


def assert_policy_invariants(data: dict):
    """Cash-value invariants that must hold whenever a Policy is read (PRD §3.9)."""
    gross = data["gross_cash_value_cents"]
    olb = data["outstanding_loan_balance_cents"]
    net = data["net_cash_value_cents"]
    assert net >= 0, "net_cash_value_cents is floored at 0"
    assert net == max(0, gross - olb), (
        f"net_cash_value_cents {net} must equal max(0, gross {gross} - olb {olb})"
    )


def assert_premium_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert data["status"] in ("POSTED", "REVERSED")


def assert_policy_loan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert data["status"] in ("ACTIVE", "SETTLED", "CALLED")


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "CONTESTING", "APPROVED", "DENIED",
    )


def assert_beneficiary(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert "version" not in data, "LedgerEntry is append-only and carries no version"
    assert "updated_at" not in data, "LedgerEntry is append-only and carries no updated_at"
    assert data["entry_type"] in (
        "PREMIUM_POSTED", "PREMIUM_REVERSED", "LOAN_DISBURSED", "LOAN_REPAID",
        "CASH_VALUE_ACCRUED", "BENEFIT_PAID", "LOAN_OFFSET",
    )
