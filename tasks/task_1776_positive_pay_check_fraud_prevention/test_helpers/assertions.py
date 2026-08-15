"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp, tolerating optional fractional seconds."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected: str):
    """Assert two ISO-8601 UTC timestamps denote the same instant (second
    precision), regardless of fractional-second formatting."""
    assert parse_utc(actual) == parse_utc(expected), (
        f"expected instant {expected}, got {actual}")


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_enrollment(data: dict):
    _assert_common(data, "TreasuryEnrollment")
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert data["tier"] in ("POSITIVE_PAY", "PAYEE_POSITIVE_PAY",
                            "REVERSE_POSITIVE_PAY")
    assert data["default_decision"] in ("PAY", "RETURN")
    assert data["deadline_mode"] in ("SAME_DAY_CUTOFF", "ROLLING_HOURS")
    assert data["status"] in ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED",
                              "TERMINATED")
    for counter in ("open_exception_count",
                    "provisional_credit_outstanding_cents",
                    "ytd_bank_loss_cents"):
        assert isinstance(data[counter], int), f"{counter} must be int"


def assert_enrollment_user(data: dict):
    _assert_common(data, "EnrollmentUser")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["user_role"] in ("ADMIN", "MANAGER", "DECISION_MAKER", "VIEWER")


def assert_account(data: dict):
    _assert_common(data, "Account")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["status"] in ("ACTIVE", "REVIEW_HOLD", "CLOSED")
    for counter in ("cumulative_paid_cents", "cumulative_reversed_cents",
                    "net_settled_cents"):
        assert isinstance(data[counter], int), f"{counter} must be int"


def assert_account_ledger_invariants(data: dict):
    """Settlement-ledger invariant (PRD §3.2): net == paid - reversed, and both
    gross counters only ever increase."""
    assert data["net_settled_cents"] == (
        data["cumulative_paid_cents"] - data["cumulative_reversed_cents"]), (
        "net_settled_cents must equal cumulative_paid_cents "
        "- cumulative_reversed_cents")


def assert_issue_file_upload(data: dict):
    _assert_common(data, "IssueFileUpload")
    assert data["status"] in ("ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED")
    assert isinstance(data["row_count"], int)
    assert isinstance(data["accepted_row_count"], int)
    assert isinstance(data["rejected_row_count"], int)
    assert data["row_count"] == data["accepted_row_count"] + data["rejected_row_count"]


def assert_issued_check(data: dict):
    _assert_common(data, "IssuedCheck")
    assert data["status"] in ("REGISTERED", "CONSUMED", "VOIDED", "STALE_DATED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_presented_item(data: dict):
    _assert_common(data, "PresentedItem")
    assert data["status"] in ("RECEIVED", "EXCEPTION_HELD", "PAID", "RETURNED",
                              "DEFAULT_PAID", "DEFAULT_RETURNED", "REVERSED")
    assert data["match_result"] in (
        "CLEAN", "NO_ISSUE_RECORD", "AMOUNT_MISMATCH", "PAYEE_MISMATCH",
        "VOIDED_ITEM", "STALE_DATED_ITEM", "DUPLICATE_PRESENTMENT",
        "REVERSE_REVIEW", "ACCOUNT_HOLD_REVIEW")


def assert_exception_item(data: dict):
    _assert_common(data, "ExceptionItem")
    assert data["status"] in ("OPEN", "DECISIONED_PAY", "DECISIONED_RETURN",
                              "DEFAULTED_PAY", "DEFAULTED_RETURN")
    assert data["reason"] in (
        "NO_ISSUE_RECORD", "AMOUNT_MISMATCH", "PAYEE_MISMATCH", "VOIDED_ITEM",
        "STALE_DATED_ITEM", "DUPLICATE_PRESENTMENT", "REVERSE_REVIEW",
        "ACCOUNT_HOLD_REVIEW")
    assert data["default_decision_snapshot"] in ("PAY", "RETURN")
    assert is_iso8601_timestamp(data.get("decision_deadline_at", ""))


def assert_ach_rule(data: dict):
    _assert_common(data, "AchDebitRule")
    assert data["rule_type"] in ("BLOCK", "FILTER")
    assert data["sec_code"] in ("CCD", "PPD", "WEB", "TEL")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "RETIRED")


def assert_fee_entry(data: dict):
    _assert_common(data, "FeeLedgerEntry")
    assert data["fee_type"] in ("EXCEPTION_FEE", "RETURN_FEE", "ADJUSTMENT",
                                "MINIMUM_TOPUP")
    assert data["status"] in ("ACCRUED", "BILLED", "WAIVED")
    assert isinstance(data["amount_cents"], int)


def assert_liability_case(data: dict):
    _assert_common(data, "LiabilityCase")
    assert data["claim_reason"] in ("FORGED_SIGNATURE", "ALTERED_AMOUNT",
                                    "COUNTERFEIT", "UNAUTHORIZED_PAYEE")
    assert data["status"] in ("FILED", "UNDER_REVIEW", "RESOLVED_BANK_LIABLE",
                              "RESOLVED_CUSTOMER_LIABLE", "RESOLVED_SHARED",
                              "WITHDRAWN")
    assert isinstance(data["claim_amount_cents"], int)
    assert isinstance(data["provisional_credit_cents"], int)


def assert_training_session(data: dict):
    _assert_common(data, "TrainingSession")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_ops_run(data: dict):
    """OpsRun is append-only (PRD §2.4): id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "OpsRun.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "OpsRun.created_at must be ISO 8601"
    assert "updated_at" not in data, "OpsRun must not carry updated_at"
    assert "version" not in data, "OpsRun must not carry version"
    assert data["kind"] in ("DAILY_SWEEP", "MONTHLY_BILLING")
    assert data["status"] == "COMPLETED"
