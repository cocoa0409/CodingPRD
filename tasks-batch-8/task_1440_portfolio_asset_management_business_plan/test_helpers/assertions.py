"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_portfolio(data: dict):
    _assert_common_fields(data, "Portfolio")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert data["risk_posture"] in ("NORMAL", "ELEVATED", "RESTRICTED")
    assert isinstance(data["total_value_cents"], int)


def assert_property_manager(data: dict):
    _assert_common_fields(data, "PropertyManager")
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["probation_streak"], int)


def assert_asset(data: dict):
    _assert_common_fields(data, "Asset")
    assert data["asset_class"] in ("OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY")
    assert data["status"] in ("OWNED", "LISTED_FOR_SALE", "UNDER_CONTRACT", "SOLD")
    assert data["net_rentable_sqft"] > 0
    assert data["acquisition_price_cents"] > 0
    assert data["hold_period_years"] > 0


def assert_business_plan(data: dict):
    _assert_common_fields(data, "BusinessPlan")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "CLOSED")
    for field in ("total_revenue_budget_cents", "total_opex_budget_cents",
                  "total_capital_budget_cents", "budgeted_noi_cents",
                  "ytd_actual_noi_cents", "available_capital_cents",
                  "reserved_capital_cents", "drawn_capital_cents", "reforecast_count"):
        assert isinstance(data[field], int), f"BusinessPlan.{field} must be an integer"


def assert_budget_line(data: dict):
    _assert_common_fields(data, "BudgetLine")
    assert data["category"] in (
        "RENT_REVENUE", "PARKING_REVENUE", "OTHER_REVENUE", "CAM_EXPENSE",
        "TAX_EXPENSE", "INSURANCE_EXPENSE", "UTILITIES_EXPENSE",
        "MANAGEMENT_FEE_EXPENSE", "OTHER_OPEX", "CAPITAL")
    assert 1 <= data["month_index"] <= 12
    assert data["budget_amount_cents"] >= 0
    assert isinstance(data["actual_amount_cents"], int)
    assert isinstance(data["has_actual"], bool)


def assert_actuals_report(data: dict):
    _assert_common_fields(data, "ActualsReport")
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert 1 <= data["month_index"] <= 12


def assert_capital_project(data: dict):
    _assert_common_fields(data, "CapitalProject")
    assert data["status"] in (
        "PROPOSED", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "REJECTED")
    assert data["requested_amount_cents"] > 0
    assert 1 <= data["sched_start_month"] <= data["sched_end_month"] <= 12


def assert_funding_draw(data: dict):
    _assert_common_fields(data, "FundingDraw")
    assert data["status"] in ("REQUESTED", "APPROVED", "RELEASED", "REJECTED")
    assert data["amount_cents"] > 0


def assert_lease_strategy(data: dict):
    _assert_common_fields(data, "LeaseStrategy")
    assert data["space_type"] in (
        "OFFICE_SUITE", "RETAIL_BAY", "INDUSTRIAL_BAY", "APARTMENT_UNIT")
    assert data["status"] in (
        "DRAFT", "RECOMMENDED", "RATIFIED", "REJECTED", "SUPERSEDED")
    assert 0 <= data["current_occupancy_pct"] <= 100


def assert_loan(data: dict):
    _assert_common_fields(data, "Loan")
    assert data["status"] in ("CURRENT", "WATCH", "DEFAULT", "REFINANCED", "PAID_OFF")
    assert data["principal_balance_cents"] > 0
    assert data["annual_interest_rate_bps"] > 0


def assert_covenant(data: dict):
    _assert_common_fields(data, "Covenant")
    assert data["covenant_type"] in ("MIN_DSCR", "MAX_LTV", "MIN_DEBT_YIELD")
    assert data["status"] in ("ACTIVE", "IN_BREACH", "WAIVED")
    assert data["threshold_bps"] > 0


def assert_covenant_test(data: dict):
    """Append-only measurement record: id + created_at only (PRD §2.4).

    PRD §2.4: "the covenant test is an append-only measurement record and
    carries only `id` and `created_at` ... `updated_at` and `version` are
    both absent from it."
    """
    assert is_valid_uuid(data.get("id", "")), "CovenantTest.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "CovenantTest.created_at must be ISO 8601"
    assert "updated_at" not in data, "CovenantTest must NOT expose updated_at"
    assert "version" not in data, "CovenantTest must NOT expose version"
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["measured_value_bps"], int)


def assert_valuation(data: dict):
    _assert_common_fields(data, "Valuation")
    assert data["method"] in ("EXTERNAL_APPRAISAL", "INTERNAL_CAP")
    assert data["status"] in ("DRAFT", "CONFIRMED", "SUPERSEDED")
    assert isinstance(data["implied_value_cents"], int)


def assert_performance_scorecard(data: dict):
    _assert_common_fields(data, "PerformanceScorecard")
    assert data["status"] in ("SUBMITTED", "REVIEWED", "FINALIZED")
    assert data["rating"] in ("EXCELLENT", "SATISFACTORY", "WATCH", "PROBATION")
    assert 0 <= data["composite_score"] <= 100


def assert_reforecast(data: dict):
    _assert_common_fields(data, "ReForecast")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPLIED", "REJECTED")
    assert data["label"] in ("R1", "R2", "R3")
    assert data["effective_from_month"] in (4, 7, 10)


def assert_disposition_decision(data: dict):
    _assert_common_fields(data, "DispositionDecision")
    assert data["trigger_type"] in ("REFINANCE", "HOLD", "SELL")
    assert data["status"] in (
        "SCREENING", "COMMITTEE_REVIEW", "RATIFIED", "EXECUTED", "SHELVED")
    assert isinstance(data["refinance_signal"], bool)
    assert isinstance(data["sell_signal"], bool)


def assert_lender_report(data: dict):
    _assert_common_fields(data, "LenderReport")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED")


def assert_capital_ledger_invariant(plan: dict):
    """PRD §3.4: "the invariant that the total capital budget equals available
    plus reserved plus drawn holds at all times."
    """
    total = plan["total_capital_budget_cents"]
    s = (plan["available_capital_cents"] + plan["reserved_capital_cents"]
         + plan["drawn_capital_cents"])
    assert total == s, (
        f"Capital ledger invariant violated: total {total} != available "
        f"{plan['available_capital_cents']} + reserved "
        f"{plan['reserved_capital_cents']} + drawn {plan['drawn_capital_cents']}")
