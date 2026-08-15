"""Entity assertions and domain invariant helpers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Full common fields: id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_timestamp_instant(actual: str, expected: str):
    """Compare two ISO-8601 UTC instants, ignoring fractional-second formatting."""
    assert isinstance(actual, str), f"expected timestamp string, got {actual!r}"

    def _norm(ts: str) -> str:
        return ts.rstrip("Z").split(".")[0]

    assert _norm(actual) == _norm(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_borrower(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] == "ACTIVE"


def assert_loan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["loan_number"], str) and data["loan_number"]
    assert data["workout_status"] in [
        "PERFORMING", "DELINQUENT", "LOSS_MIT_REVIEW", "TRIAL",
        "MOD_PENDING", "PERMANENTLY_MODIFIED",
    ]
    assert data["foreclosure_status"] in [
        "NONE", "REFERRED", "SALE_SCHEDULED", "SALE_HOLD", "SALE_COMPLETED",
    ]
    for field in (
        "unpaid_principal_balance_cents", "interest_rate_bp",
        "remaining_term_months", "arrears_cents", "suspense_cents",
        "deferred_principal_cents", "escrow_balance_cents",
        "escrow_monthly_cents", "current_pi_cents", "delinquency_days",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_application(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED", "ACKNOWLEDGED", "COMPLETE_PACKAGE", "EVALUATED_OFFER",
        "EVALUATED_DENIAL", "APPEAL_REVIEW", "TRIAL_ACTIVE", "TRIAL_PASSED",
        "APPROVED", "CLOSED_DENIED", "WITHDRAWN",
    ]
    assert isinstance(data["verified_monthly_income_cents"], int)
    assert isinstance(data["outstanding_doc_categories"], list)
    assert isinstance(data["stated_monthly_income_cents"], int)


def assert_document(data: dict):
    assert_common_fields(data)
    assert data["doc_type"] in [
        "PAYSTUB", "TAX_RETURN", "PROFIT_LOSS", "BANK_STATEMENT", "HARDSHIP_AFFIDAVIT",
    ]
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED"]


def assert_program_option(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["waterfall_rank"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_evaluation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]
    assert data["result"] in ["OFFER", "DENIAL"]
    assert isinstance(data["denial_reasons"], list)


def assert_step_result(data: dict):
    """Step rows are immutable snapshots: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "step id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "step created_at must be ISO 8601 UTC"
    )
    assert "version" not in data, "step rows must not expose version"
    assert "updated_at" not in data, "step rows must not expose updated_at"
    assert isinstance(data["program_code"], str)
    assert isinstance(data["step_rank"], int)
    assert isinstance(data["eligible"], bool)
    assert isinstance(data["selected"], bool)


def assert_trial_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OFFERED", "ACTIVE", "COMPLETED", "FAILED", "CANCELLED"]
    assert isinstance(data["trial_payment_cents"], int)
    assert data["periods"] == 3


def assert_trial_payment(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "SCHEDULED", "PAID_ON_TIME", "PAID_LATE", "PAID_INSUFFICIENT", "MISSED",
    ]
    assert isinstance(data["scheduled_amount_cents"], int)
    assert data["period_index"] in (1, 2, 3)


def assert_modification(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "DOCS_SENT", "SIGNED", "RECORDED", "RESCINDED"]
    for field in (
        "final_base_cents", "final_rate_bp", "final_term_months",
        "final_forbearance_cents", "final_pi_cents", "capitalized_arrears_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_denial_notice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ISSUED", "APPEALED", "SUPERSEDED", "AFFIRMED"]
    assert isinstance(data["reasons"], list)
    assert isinstance(data["appeal_eligible"], bool)


def assert_appeal(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "AFFIRMED", "OVERTURNED"]


def assert_foreclosure_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "REFERRED", "SALE_SCHEDULED", "SALE_HOLD", "SALE_COMPLETED", "CANCELLED",
    ]


def assert_escrow_analysis(data: dict):
    assert_common_fields(data)
    assert data["analysis_type"] in ["STANDARD_ANNUAL", "POST_MODIFICATION"]
    assert data["status"] in ["DRAFT", "APPLIED", "VOIDED", "CANCELLED"]
    for field in (
        "cushion_cents", "balance_at_analysis_cents", "shortage_cents",
        "surplus_cents", "monthly_spread_cents", "spread_last_month_cents",
        "new_monthly_escrow_cents", "refund_cents", "credit_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
