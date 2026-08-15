"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """Every primary resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_loss_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["method"] in ("LOSS_RATE", "DISCOUNTED_CASH_FLOW", "VINTAGE")
    assert isinstance(data["forecast_period_quarters"], int)
    assert data["reversion_method"] in ("IMMEDIATE", "STRAIGHT_LINE")
    assert isinstance(data["reversion_period_quarters"], int)
    assert isinstance(data["historical_lookback_quarters"], int)
    assert isinstance(data["version_label"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert isinstance(data["consecutive_backtest_breach_count"], int)
    assert isinstance(data["refresh_required"], bool)


def assert_portfolio_segment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["segment_code"], str) and len(data["segment_code"]) > 0
    assert data["product_type"] in ("CREDIT_CARD", "AUTO", "MORTGAGE", "SMALL_BUSINESS", "PERSONAL")
    assert data["risk_rating_band"] in ("PRIME", "NEAR_PRIME", "SUBPRIME", "DEEP_SUBPRIME")
    assert isinstance(data["vintage_year"], int)
    assert data["status"] in ("OPEN", "WATCH")
    assert isinstance(data["origination_total_cents"], int)
    assert isinstance(data["ytd_gross_charge_offs_cents"], int)
    assert isinstance(data["ytd_recoveries_cents"], int)
    assert isinstance(data["charge_off_rate_bps"], int)
    assert isinstance(data["base_loss_rate_bps"], int)


def assert_loan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["segment_id"], str)
    assert isinstance(data["loan_number"], str) and len(data["loan_number"]) > 0
    assert isinstance(data["amortized_cost_cents"], int)
    assert data["risk_rating"] in ("PASS", "SPECIAL_MENTION", "SUBSTANDARD", "DOUBTFUL", "LOSS")
    assert isinstance(data["delinquency_days"], int)
    assert isinstance(data["collateral_value_cents"], int)
    assert isinstance(data["individually_evaluated"], bool)
    assert data["status"] in ("ACTIVE", "CHARGED_OFF")
    assert isinstance(data["charged_off_total_cents"], int)
    assert isinstance(data["recovered_total_cents"], int)


def assert_economic_scenario(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["scenario_type"] in ("BASELINE", "ADVERSE", "OPTIMISTIC")
    assert isinstance(data["unemployment_rate_bps"], int)
    assert isinstance(data["gdp_growth_bps"], int)
    assert isinstance(data["effective_from_period"], str)
    assert isinstance(data["effective_to_period"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_qualitative_factor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["segment_id"], str)
    assert data["factor_code"] in (
        "CONCENTRATION_RISK", "POLICY_CHANGE", "ECONOMIC_UNCERTAINTY",
        "COLLATERAL_VALUATION", "MODEL_LIMITATION",
    )
    assert isinstance(data["adjustment_bps"], int)
    assert isinstance(data["effective_from_period"], str)
    assert isinstance(data["effective_to_period"], str)
    assert data["status"] in ("DRAFT", "DOCUMENTED", "APPROVED", "RETIRED")


def assert_model_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["as_of_period"], str)
    assert isinstance(data["loss_model_id"], str)
    assert isinstance(data["scenario_weights"], list)
    assert data["status"] in ("DRAFT", "EXECUTED", "UNDER_REVIEW", "APPROVED", "FINALIZED")
    assert isinstance(data["individual_evaluation_count"], int)
    assert isinstance(data["reviewed_evaluation_count"], int)
    assert isinstance(data["total_exposure_cents"], int)
    assert isinstance(data["quantitative_reserve_cents"], int)
    assert isinstance(data["qualitative_adjustment_cents"], int)
    assert isinstance(data["individual_reserve_cents"], int)
    assert isinstance(data["management_adjustment_cents"], int)
    assert isinstance(data["total_allowance_cents"], int)
    assert isinstance(data["segments_breakdown"], list)


def assert_individual_evaluation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["loan_id"], str)
    assert data["method"] in ("COLLATERAL_FAIR_VALUE", "DISCOUNTED_CASH_FLOW")
    assert isinstance(data["collateral_value_cents"], int)
    assert isinstance(data["specific_reserve_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "REVIEWED")


def assert_management_adjustment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["rationale"], str)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")
    assert isinstance(data["created_by_user_id"], str)


def assert_disclosure_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["beginning_allowance_cents"], int)
    assert isinstance(data["ending_allowance_cents"], int)
    assert isinstance(data["period_charge_offs_cents"], int)
    assert isinstance(data["period_recoveries_cents"], int)
    assert isinstance(data["provision_cents"], int)
    assert data["status"] in ("PREPARED", "UNDER_AUDIT_REVIEW", "RELEASED")


def assert_backtest_result(data: dict):
    """Back-test results carry only id + created_at as common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "back-test results must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "back-test results must not carry version (PRD §2.4)"
    assert isinstance(data["loss_model_id"], str)
    assert isinstance(data["backtest_period"], str)
    assert isinstance(data["actual_loss_rate_bps"], int)
    assert isinstance(data["predicted_loss_rate_bps"], int)
    assert isinstance(data["variance_bps"], int)
    assert data["outcome"] in ("PASS", "BREACH")


def assert_model_run_totals(data: dict):
    """Run totals invariant: the total allowance is the sum of the four components (PRD §3.6)."""
    assert data["total_allowance_cents"] == (
        data["quantitative_reserve_cents"]
        + data["qualitative_adjustment_cents"]
        + data["individual_reserve_cents"]
        + data["management_adjustment_cents"]
    ), (
        "total_allowance_cents must equal quantitative + qualitative + "
        f"individual + management adjustment: {data}"
    )


def assert_rollforward_identity(report: dict):
    """Roll-forward identity: ending == beginning + provision - net charge-offs (PRD §3.8)."""
    net_charge_offs = report["period_charge_offs_cents"] - report["period_recoveries_cents"]
    assert report["ending_allowance_cents"] == (
        report["beginning_allowance_cents"] + report["provision_cents"] - net_charge_offs
    ), f"Roll-forward identity violated: {report}"
