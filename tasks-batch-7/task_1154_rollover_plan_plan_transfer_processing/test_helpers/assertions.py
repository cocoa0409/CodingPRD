"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_plan(data: dict):
    _assert_common_fields(data, "Plan")
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert data["plan_type"] in ["PLAN_401K", "PLAN_403B", "PLAN_457B", "IRA"]
    assert data["status"] in ["ACTIVE", "FROZEN", "TERMINATED"]


def assert_freeze_window(data: dict):
    _assert_common_fields(data, "PlanFreezeWindow")
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_participant(data: dict):
    _assert_common_fields(data, "Participant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["employment_status"] in ["ACTIVE", "SEPARATED", "RETIRED", "DISABLED"]
    assert data["marital_status"] in ["SINGLE", "MARRIED", "WIDOWED", "DIVORCED"]


def assert_account(data: dict):
    _assert_common_fields(data, "Account")
    assert data["status"] in ["ACTIVE", "CLOSED"]
    assert isinstance(data["total_balance_cents"], int)
    assert isinstance(data["vested_balance_cents"], int)
    assert isinstance(data["basis_cents"], int)


def assert_account_invariants(data: dict):
    """Domain invariants that must hold on any account read (PRD §3.2)."""
    assert data["total_balance_cents"] >= 0
    assert data["vested_balance_cents"] >= 0
    assert data["basis_cents"] >= 0
    assert data["vested_balance_cents"] <= data["total_balance_cents"]


def assert_money_source_balance(data: dict):
    _assert_common_fields(data, "MoneySourceBalance")
    assert data["source_type"] in ["PRE_TAX", "EMPLOYER_PRETAX", "ROTH", "AFTER_TAX"]
    assert data["balance_cents"] >= 0
    assert data["basis_cents"] >= 0
    if data["basis_cents"] > 0:
        assert data["basis_cents"] <= data["balance_cents"]
    assert 0 <= data["vested_pct"] <= 100


def assert_loan(data: dict):
    _assert_common_fields(data, "Loan")
    assert data["status"] in ["ACTIVE", "TRANSFERRED", "OFFSET"]
    assert data["outstanding_balance_cents"] > 0


def assert_rollover_case(data: dict):
    _assert_common_fields(data, "RolloverCase")
    assert data["case_type"] in [
        "DIRECT_ROLLOVER_OUT", "INDIRECT_ROLLOVER_OUT", "PLAN_TRANSFER",
        "IN_PLAN_ROTH_CONVERSION", "ROLLOVER_IN",
    ]
    assert data["status"] in [
        "DRAFT", "DOCS_PENDING", "ELIGIBILITY_REVIEW", "ELIGIBLE", "DENIED",
        "DISBURSED", "AWAITING_REDEPOSIT", "ACCEPTANCE_PENDING", "SUSPENDED",
        "COMPLETED", "INCOMPLETE", "CANCELLED",
    ]


def assert_required_document(data: dict):
    _assert_common_fields(data, "RequiredDocument")
    assert data["doc_type"] in [
        "SPOUSAL_CONSENT", "SEPARATION_VERIFICATION", "DISABILITY_PROOF",
        "IDENTITY_PROOF", "RECEIVING_PLAN_ACCEPTANCE", "SOURCE_PLAN_STATEMENT",
    ]
    assert data["status"] in ["REQUIRED", "SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_source_plan_verification(data: dict):
    _assert_common_fields(data, "SourcePlanVerification")
    assert data["direction"] in ["OUTBOUND", "INBOUND"]
    assert data["method"] in ["PLAN_LETTER", "IRS_FORM_LOOKUP", "THIRD_PARTY_REGISTRY"]
    assert data["status"] in ["PENDING", "VERIFIED", "FAILED"]


def assert_disbursement(data: dict):
    _assert_common_fields(data, "Disbursement")
    assert data["method"] in ["CHECK", "ACH", "WIRE", "INTERNAL_BOOK_ENTRY"]
    assert data["status"] in ["PENDING", "ISSUED", "RETURNED", "CANCELLED"]


def assert_disbursement_snapshot_invariant(data: dict):
    """PRD §3.6: gross_cents == withholding_cents + net_cents always holds."""
    assert data["gross_cents"] == data["withholding_cents"] + data["net_cents"], (
        f"disbursement snapshot invariant violated: {data}"
    )


def assert_redeposit(data: dict):
    _assert_common_fields(data, "Redeposit")
    assert data["status"] in ["PENDING_VERIFICATION", "CREDITED", "REJECTED"]
    assert data["amount_cents"] > 0


def assert_follow_up_notice(data: dict):
    _assert_common_fields(data, "FollowUpNotice")
    assert data["status"] in ["SCHEDULED", "SENT", "SKIPPED"]
    assert data["notice_seq"] in [1, 2, 3]


def assert_tax_form(data: dict):
    _assert_common_fields(data, "TaxForm")
    assert data["form_type"] in ["FORM_1099_R", "FORM_5498"]
    assert data["status"] in ["DRAFT", "ISSUED", "SUPERSEDED"]
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["revision"], int) and data["revision"] >= 0
