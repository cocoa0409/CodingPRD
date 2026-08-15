"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict):
    """Primary resources share id / created_at / updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_ledger_fields(data: dict):
    """Ledger-style records carry only id + created_at among common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger records must not expose updated_at"
    assert "version" not in data, "ledger records must not expose version"


def _assert_money(value, name):
    assert isinstance(value, (int, float)), f"{name} must be a JSON number"
    assert_cost_precision(float(value), 2)


def assert_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fund_name"], str) and data["fund_name"]
    assert data["fund_type"] in ("DONOR_ADVISED", "DESIGNATED", "SCHOLARSHIP")
    assert data["status"] in ("PENDING_AGREEMENT", "ACTIVE", "INACTIVE", "DORMANT", "CLOSED")
    assert isinstance(data["endowed"], bool)
    _assert_money(data["cash_balance"], "cash_balance")
    assert isinstance(data["invested_units"], (int, float))
    _assert_money(data["invested_market_value"], "invested_market_value")
    _assert_money(data["total_market_value"], "total_market_value")
    _assert_money(data["spendable_balance"], "spendable_balance")
    _assert_money(data["current_spending_allowance"], "current_spending_allowance")
    _assert_money(data["allowance_used"], "allowance_used")


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "EXECUTED", "SUPERSEDED", "TERMINATED")
    assert data["spending_formula"] in ("AVERAGE_12Q", "FIXED_3YR")
    assert data["fee_tier_schedule"] in ("STANDARD", "FLAT")
    _assert_money(data["spending_rate_pct"], "spending_rate_pct")
    assert isinstance(data["agreement_version_no"], int)


def assert_advisor(data: dict):
    _assert_common_fields(data)
    assert data["advisor_kind"] in ("PRIMARY", "SUCCESSOR")
    assert data["status"] in ("INVITED", "ACTIVE", "RESIGNED", "DECEASED", "REVOKED")
    assert isinstance(data["email"], str) and data["email"]


def assert_contribution(data: dict):
    _assert_common_fields(data)
    assert data["asset_kind"] in ("CASH", "PUBLICLY_TRADED", "RESTRICTED_STOCK", "REAL_PROPERTY")
    assert data["acceptance_status"] in ("PLEDGED", "ACCEPTED", "DECLINED")
    assert data["liquidation_status"] in ("NOT_REQUIRED", "PENDING_LIQUIDATION", "LIQUIDATED")
    _assert_money(data["declared_value"], "declared_value")


def assert_asset_lot(data: dict):
    _assert_ledger_fields(data)
    assert isinstance(data["description"], str)
    assert data["quantity"] > 0
    _assert_money(data["appraised_value"], "appraised_value")


def assert_pool(data: dict):
    _assert_common_fields(data)
    assert data["pool_kind"] in ("CONSERVATIVE", "BALANCED", "GROWTH")
    assert data["status"] in ("OPEN", "SUSPENDED", "TERMINATED")
    _assert_money(data["nav"], "nav")
    assert isinstance(data["units_outstanding"], (int, float))
    if data["units_outstanding"] > 0:
        assert isinstance(data["unit_price"], (int, float))


def assert_pool_holding(data: dict):
    _assert_common_fields(data)
    assert data["units_held"] > 0


def assert_unitization_event(data: dict):
    _assert_ledger_fields(data)
    assert data["event_kind"] in ("BUY_IN", "REDEMPTION", "MARK_TO_MARKET")
    assert isinstance(data["unit_price_applied"], (int, float))
    assert isinstance(data["units_delta"], (int, float))


def assert_grantee(data: dict):
    _assert_common_fields(data)
    assert data["irs_subsection"] in ("C3_501", "C3_PRIVATE_FOUNDATION", "GOVERNMENT", "OTHER")
    assert data["due_diligence_status"] in (
        "UNVETTED", "IN_REVIEW", "CLEARED", "REJECTED_DD", "EXPIRED"
    )
    assert isinstance(data["expenditure_responsibility_required"], bool)


def assert_grant(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "COMPLIANCE_REVIEW", "APPROVED",
        "DISBURSED", "RETURNED", "DENIED", "CANCELLED",
    )
    _assert_money(data["amount"], "amount")
    assert isinstance(data["revision_count"], int)


def assert_disbursement(data: dict):
    _assert_ledger_fields(data)
    assert data["source_kind"] in ("GRANT", "SCHOLARSHIP_AWARD")
    _assert_money(data["amount"], "amount")


def assert_spending_run(data: dict):
    _assert_ledger_fields(data)
    assert data["formula_used"] in ("AVERAGE_12Q", "FIXED_3YR")
    _assert_money(data["base_value"], "base_value")
    _assert_money(data["allowance_granted"], "allowance_granted")
    assert isinstance(data["market_values_used"], list)


def assert_snapshot(data: dict):
    _assert_ledger_fields(data)
    assert data["snapshot_kind"] in ("QUARTER_END", "FISCAL_YEAR_END")
    _assert_money(data["market_value"], "market_value")


def assert_fee_assessment(data: dict):
    _assert_ledger_fields(data)
    assert data["schedule_used"] in ("STANDARD", "FLAT")
    _assert_money(data["annual_fee"], "annual_fee")
    _assert_money(data["quarterly_fee"], "quarterly_fee")


def assert_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SETUP", "OPEN", "SCORING", "AWARDED", "CLOSED", "CANCELLED")
    _assert_money(data["award_amount"], "award_amount")
    assert isinstance(data["max_awards"], int) and data["max_awards"] >= 1
    assert isinstance(data["committee_size"], int)
    assert isinstance(data["quorum_threshold"], int)


def assert_committee_member(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SEATED", "RECUSED", "REMOVED")


def assert_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "UNDER_SCORING", "SELECTED", "NOT_SELECTED",
        "ACCEPTED_AWARD", "DECLINED_AWARD",
    )


def assert_score_entry(data: dict):
    _assert_ledger_fields(data)
    for component in ("academic", "financial_need", "essay", "interview"):
        assert 0 <= data[component] <= 100, f"{component} must be within [0, 100]"
    _assert_money(data["weighted_score"], "weighted_score")


def assert_award(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DISBURSED", "DECLINED", "FORFEITED")
    _assert_money(data["amount"], "amount")


def assert_statement(data: dict):
    _assert_ledger_fields(data)
    assert data["status"] in ("GENERATED", "DELIVERED")
    for field in (
        "opening_value", "contributions_total", "grants_total",
        "fees_total", "closing_value", "investment_gain_loss",
    ):
        _assert_money(data[field], field)


def assert_money_eq(actual, expected, label):
    """Compare a 2dp monetary value against an exact expectation (round-half-up domain)."""
    assert float(actual) == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_units_eq(actual, expected, label):
    """Compare a 4dp unit quantity against an exact expectation."""
    assert float(actual) == pytest.approx(expected, abs=0.00001), (
        f"{label}: expected {expected}, got {actual}"
    )
