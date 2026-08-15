"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version starts at 1 and increments on every mutation"
    )


def _assert_lean_fields(data: dict):
    """Rent roll entries and proration lines carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lean records carry no updated_at"
    assert "version" not in data, "lean records carry no version"


def assert_acquisition(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_name"], str) and data["property_name"]
    assert isinstance(data["agreed_purchase_price_cents"], int)
    assert isinstance(data["earnest_money_cents"], int)
    assert isinstance(data["prior_year_tax_cents"], int)
    assert data["status"] in [
        "DRAFT", "IN_DILIGENCE", "DILIGENCE_COMPLETE", "PRE_CLOSING",
        "CLOSED", "SETTLED", "TERMINATED",
    ]
    assert data["readiness_posture"] in ["ON_TRACK", "AT_RISK", "BLOCKED"]
    for field in ("deferred_maintenance_total_cents", "rent_roll_variance_cents",
                  "deposit_variance_cents", "payroll_accrual_cents",
                  "net_proration_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert data["status"] in ["REGISTERED", "CLEARING", "VERIFIED", "EXCLUDED"]
    for flag in ("lease_audited", "walk_accepted", "deposit_reconciled"):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"


def assert_lease_file(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_rent_cents"], int)
    assert isinstance(data["term_months"], int)
    assert data["status"] in [
        "UPLOADED", "AUDITED", "DISCREPANCY_FLAGGED", "RESOLVED", "WAIVED",
        "SUPERSEDED",
    ]


def assert_rent_roll_entry(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["reported_rent_cents"], int)
    assert data["verification_status"] in ["UNVERIFIED", "VERIFIED", "MISMATCHED"]


def assert_concession(data: dict):
    _assert_common_fields(data)
    assert data["concession_type"] in [
        "RECURRING_MONTHLY", "ONE_TIME_CREDIT", "FREE_MONTH_AMORTIZED",
    ]
    assert data["verification_status"] in ["PENDING", "VERIFIED", "REJECTED"]


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "QA_ACCEPTED", "QA_REJECTED"]
    assert isinstance(data["reschedule_count"], int)


def assert_finding(data: dict):
    _assert_common_fields(data)
    assert data["category"] in [
        "LIFE_SAFETY", "MAJOR_SYSTEMS", "CODE_COMPLIANCE", "COSMETIC",
    ]
    assert 1 <= data["severity"] <= 5
    assert data["status"] in ["OPEN", "VERIFIED", "DISPUTED", "EXCLUDED"]


def assert_utility_record(data: dict):
    _assert_common_fields(data)
    assert data["category"] in ["ELECTRIC", "GAS", "WATER_SEWER", "TRASH", "OTHER"]
    assert data["source"] in ["SELLER_T12", "BILL_AUDIT", "ESTIMATE"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["is_outlier"], bool)
    assert isinstance(data["normalized_amount_cents"], int)


def assert_tax_projection(data: dict):
    _assert_common_fields(data)
    assert data["method"] in ["PURCHASE_PRICE_ANCHORED", "INCOME_APPROACH"]
    assert data["status"] in ["DRAFT", "COMPUTED", "APPROVED", "SUPERSEDED"]


def assert_deposit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["seller_stated_amount_cents"], int)
    assert isinstance(data["interest_required"], bool)
    assert data["status"] in [
        "RECORDED", "RECONCILED", "DISPUTED", "ESCROW_QUEUED", "TRANSFERRED",
    ]


def assert_employee_decision(data: dict):
    _assert_common_fields(data)
    assert data["decision"] in ["RETAIN", "TERMINATE", "TRANSFER"]
    assert data["status"] in [
        "PROPOSED", "APPROVED", "REJECTED", "NOTIFIED", "EFFECTIVE", "RESCINDED",
    ]


def assert_service_contract(data: dict):
    _assert_common_fields(data)
    assert data["service_type"] in [
        "ELEVATOR", "LAUNDRY", "LANDSCAPING", "PEST_CONTROL", "SECURITY", "OTHER",
    ]
    assert data["status"] in [
        "IDENTIFIED", "UNDER_REVIEW", "ASSUMED", "NOTICE_SENT",
        "CANCELLED_EFFECTIVE", "RENEWED", "AUTO_RENEWED", "TRANSFERRED",
    ]


def assert_insurance_policy(data: dict):
    _assert_common_fields(data)
    assert data["policy_type"] in [
        "PROPERTY", "GENERAL_LIABILITY", "UMBRELLA", "FLOOD", "OTHER",
    ]
    assert data["status"] in [
        "DOCUMENTED", "LOSS_RUNS_REVIEWED", "ASSUMED", "TRANSFERRED", "EXCLUDED",
    ]


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert data["statement_type"] in [
        "DRAFT_CLOSING", "FINAL_CLOSING", "POST_CLOSING_TRUEUP",
    ]
    assert data["day_count_method"] in ["ACTUAL_365", "BANKERS_30_360"]
    assert data["status"] in ["DRAFT", "REVIEWED", "APPROVED", "SETTLED", "SUPERSEDED"]
    for field in ("total_buyer_credits_cents", "total_seller_credits_cents",
                  "net_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_proration_line(data: dict):
    _assert_lean_fields(data)
    assert data["line_type"] in [
        "RENT", "TAX", "PREPAID_EXPENSE", "DEPOSIT_TRANSFER", "PAYROLL", "ADJUSTMENT",
    ]
    assert data["direction"] in ["CREDIT_BUYER", "CREDIT_SELLER"]
    assert data["source_kind"] in ["GENERATED", "MANUAL"]
    assert isinstance(data["amount_cents"], int)


def assert_adjustment(data: dict):
    _assert_common_fields(data)
    assert data["adjustment_type"] in [
        "COLLECTION_LOSS", "TAX_RECALC", "DEPOSIT_SHORTFALL", "EXPENSE_RECON",
    ]
    assert data["direction"] in ["CREDIT_BUYER", "CREDIT_SELLER"]
    assert data["status"] in [
        "ASSERTED", "EVIDENCED", "ACCEPTED", "DISPUTED", "RESOLVED", "APPLIED",
    ]


def assert_statement_netting_invariant(statement: dict):
    """PRD §3.8: net is buyer credits minus seller credits, always."""
    assert statement["net_amount_cents"] == (
        statement["total_buyer_credits_cents"] - statement["total_seller_credits_cents"]
    ), "net_amount_cents must equal buyer credits minus seller credits"
