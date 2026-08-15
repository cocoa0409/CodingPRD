"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Every resource carries the standard
system-managed quartet (id, created_at, updated_at, version); covenant ratios
are carried to exactly four decimal places and money is integer cents.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PAYMENT_STATUSES = ("CURRENT", "DELINQUENT", "DEFAULT", "MATURITY_DEFAULT")
SERVICING_STATUSES = ("PERFORMING", "WATCHLIST", "SPECIAL_SERVICING")
STATEMENT_TYPES = ("RENT_ROLL", "OPERATING_STATEMENT")
STATEMENT_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED")
ASSESSMENT_TYPES = ("DSCR", "LTV")
ASSESSMENT_STATUSES = ("OPEN", "CONFORMING", "CURED", "WAIVED")
RESERVE_ACCOUNT_TYPES = ("TI_LC", "REPLACEMENT")
DISBURSEMENT_PURPOSES = ("TENANT_IMPROVEMENT", "LEASING_COMMISSION", "CAPITAL_REPAIR")
DISBURSEMENT_STATUSES = ("SUBMITTED", "APPROVED", "FUNDED", "REJECTED", "CANCELLED")
LEASE_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "CONDITIONALLY_APPROVED", "REJECTED")
ESTOPPEL_STATUSES = ("PENDING", "EXECUTED", "EXPIRED")
INSPECTION_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
CONDITION_RATINGS = ("GOOD", "FAIR", "POOR", "CRITICAL")
COVERAGE_TYPES = ("PROPERTY", "LIABILITY", "FLOOD")
POLICY_STATUSES = ("ACTIVE", "EXPIRED", "CANCELLED")
ASSUMPTION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED",
                       "EXECUTED", "WITHDRAWN")
EXTENSION_OPTION_STATUSES = ("AVAILABLE", "EXERCISED", "EXPIRED", "SUSPENDED")
WATCHLIST_CRITERIA = ("REPORTING_DELINQUENCY", "POOR_INSPECTION", "INSURANCE_LAPSE",
                      "MATURITY_RISK", "RISK_SCORE")
WATCHLIST_STATUSES = ("ACTIVE", "RESOLVED", "ESCALATED")
PROPERTY_TYPES = ("OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY", "HOTEL")


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601 UTC")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601 UTC")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}")


def assert_ratio_4dp(value):
    """Covenant ratios are carried to exactly four decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    assert round(float(value), 4) == float(value), (
        f"Ratio {value!r} exceeds four decimal places")


def assert_borrower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_loan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["borrower_id"], str)
    assert isinstance(data["loan_number"], str) and data["loan_number"]
    assert isinstance(data["original_principal_cents"], int)
    assert data["original_principal_cents"] > 0
    assert isinstance(data["current_balance_cents"], int)
    assert data["current_balance_cents"] >= 0
    assert isinstance(data["note_rate"], (int, float))
    assert 0 < data["note_rate"] < 1
    assert data["payment_status"] in PAYMENT_STATUSES
    assert data["servicing_status"] in SERVICING_STATUSES
    assert data["dscr_basis"] in ("TTM", "T3_ANNUALIZED")
    assert data["assumption_fee_basis"] in ("OUTSTANDING", "ORIGINAL")
    assert isinstance(data["capitalized_advances_cents"], int)
    assert data["capitalized_advances_cents"] >= 0
    assert isinstance(data["days_delinquent"], int) and data["days_delinquent"] >= 0
    if data.get("current_dscr") is not None:
        assert_ratio_4dp(data["current_dscr"])
    if data.get("current_ltv") is not None:
        assert_ratio_4dp(data["current_ltv"])


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_id"], str)
    assert isinstance(data["address"], str) and data["address"]
    assert data["property_type"] in PROPERTY_TYPES
    assert isinstance(data["appraised_value_cents"], int)
    assert data["appraised_value_cents"] > 0
    assert isinstance(data["appraisal_date"], str)


def assert_financial_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_id"], str)
    assert data["statement_type"] in STATEMENT_TYPES
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["submitted_late"], bool)
    assert data["status"] in STATEMENT_STATUSES


def assert_covenant_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_id"], str)
    assert data["assessment_type"] in ASSESSMENT_TYPES
    assert data["status"] in ASSESSMENT_STATUSES
    assert isinstance(data["breach"], bool)
    assert isinstance(data["threshold_value"], (int, float))
    assert isinstance(data["assessed_at"], str)
    if data.get("computed_value") is not None:
        assert_ratio_4dp(data["computed_value"])
    if data["assessment_type"] == "DSCR":
        assert data.get("statement_id"), "DSCR assessment points at its source statement"
        assert data["basis"] in ("TTM", "T3_ANNUALIZED")
    else:
        assert data.get("statement_id") is None
        assert data.get("basis") is None
    if data["status"] != "WAIVED":
        assert data.get("waived_by_user_id") is None, (
            "waived_by_user_id stays null on every non-waived assessment")


def assert_reserve_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_id"], str)
    assert data["account_type"] in RESERVE_ACCOUNT_TYPES
    for field in ("balance_cents", "held_cents", "retained_cents",
                  "target_balance_cents", "available_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["elevated_retainage"], bool)
    assert isinstance(data["disbursement_frozen"], bool)


def assert_reserve_invariants(data: dict):
    """available_cents is always balance minus held, and never negative."""
    assert_reserve_account(data)
    assert data["available_cents"] == data["balance_cents"] - data["held_cents"], (
        f"available {data['available_cents']} != balance {data['balance_cents']} "
        f"- held {data['held_cents']}")
    assert data["available_cents"] >= 0, "available_cents must never go negative"


def assert_disbursement_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["reserve_account_id"], str)
    assert data["purpose"] in DISBURSEMENT_PURPOSES
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    for item in data["line_items"]:
        assert isinstance(item["description"], str)
        assert isinstance(item["amount_cents"], int) and item["amount_cents"] > 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["amount_cents"] == sum(i["amount_cents"] for i in data["line_items"]), (
        "amount_cents is the sum of the line items")
    assert data["status"] in DISBURSEMENT_STATUSES
    assert isinstance(data["funded_cents"], int) and data["funded_cents"] >= 0
    assert isinstance(data["retained_cents"], int) and data["retained_cents"] >= 0
    if data["status"] != "FUNDED":
        assert data.get("funded_at") is None, "funded_at stays null until funding"


def assert_lease(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["tenant_name"], str) and data["tenant_name"]
    assert isinstance(data["suite_ref"], str) and data["suite_ref"]
    assert isinstance(data["base_rent_cents_monthly"], int)
    assert data["base_rent_cents_monthly"] > 0
    assert isinstance(data["sqft"], int) and data["sqft"] > 0
    assert isinstance(data["term_months"], int) and data["term_months"] > 0
    assert data["status"] in LEASE_STATUSES
    assert isinstance(data["lender_approval_required"], bool)
    assert isinstance(data["estoppel_required"], bool)
    assert data["estoppel_required"] == data["lender_approval_required"], (
        "estoppel_required mirrors lender_approval_required")


def assert_estoppel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str)
    assert data["status"] in ESTOPPEL_STATUSES
    assert isinstance(data["due_date"], str)
    if data["status"] == "PENDING":
        assert data.get("executed_at") is None, "executed_at stays null until execution"


def assert_inspector(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_no"], str) and data["license_no"]
    assert isinstance(data["active"], bool)


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert data["status"] in INSPECTION_STATUSES
    if data["status"] != "COMPLETED":
        assert data.get("completed_at") is None, "completed_at stays null until completion"
    if data.get("condition_rating") is not None:
        assert data["condition_rating"] in CONDITION_RATINGS


def assert_insurance_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert data["coverage_type"] in COVERAGE_TYPES
    assert isinstance(data["coverage_amount_cents"], int)
    assert data["coverage_amount_cents"] > 0
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in POLICY_STATUSES
    assert isinstance(data["force_placed"], bool)
    assert isinstance(data["premium_advance_cents"], int)
    assert data["premium_advance_cents"] >= 0


def assert_assumption_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_id"], str)
    assert isinstance(data["proposed_assumptor_name"], str)
    assert data["proposed_assumptor_name"]
    assert isinstance(data["proposed_assumptor_tax_id"], str)
    assert data["proposed_assumptor_tax_id"]
    assert isinstance(data["proposed_net_worth_cents"], int)
    assert data["proposed_net_worth_cents"] >= 0
    assert data["status"] in ASSUMPTION_STATUSES
    if data["status"] in ("SUBMITTED", "UNDER_REVIEW"):
        assert data.get("fee_cents") is None, "fee_cents stays null until approval"


def assert_extension_option(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_id"], str)
    assert isinstance(data["option_seq"], int) and data["option_seq"] >= 1
    assert isinstance(data["exercise_window_start"], str)
    assert isinstance(data["exercise_window_end"], str)
    assert isinstance(data["extension_months"], int) and data["extension_months"] > 0
    assert isinstance(data["fee_pct"], (int, float)) and data["fee_pct"] >= 0
    assert data["status"] in EXTENSION_OPTION_STATUSES
    if data["status"] != "EXERCISED":
        assert data.get("exercised_fee_cents") is None, (
            "exercised_fee_cents stays null until the option is exercised")


def assert_watchlist_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loan_id"], str)
    assert data["criterion"] in WATCHLIST_CRITERIA
    assert data["status"] in WATCHLIST_STATUSES
    assert isinstance(data["escalation_review"], bool)
    if data["criterion"] != "RISK_SCORE":
        assert data.get("risk_score_at_creation") is None, (
            "risk_score_at_creation is null on entries of every other criterion")
    if data["status"] == "ACTIVE":
        assert data.get("resolved_at") is None, (
            "resolved_at stays null while the entry remains ACTIVE")
