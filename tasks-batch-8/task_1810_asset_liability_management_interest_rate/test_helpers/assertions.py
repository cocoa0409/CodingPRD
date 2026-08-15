"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_NUM = (int, float)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_alm_book(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_curve_rate_bps"], int)
    assert isinstance(data["min_hedged_notional_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE")
    for field in ("total_assets_cents", "total_liabilities_cents",
                  "hedged_notional_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["total_assets_cents"] >= 0
    assert data["total_liabilities_cents"] >= 0
    assert data["hedged_notional_cents"] >= 0


def assert_position(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert data["category"] in ("LOAN", "SECURITY", "DEPOSIT", "BORROWING")
    if data["category"] == "DEPOSIT":
        assert data["deposit_segment"] in (
            "RETAIL_NONMATURITY", "BUSINESS_NONMATURITY", "TIME")
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] > 0
    assert isinstance(data["rate_bps"], int) and data["rate_bps"] >= 0
    assert isinstance(data["scheduled_runoff_pct"], _NUM)
    assert 0 <= data["scheduled_runoff_pct"] <= 100
    assert isinstance(data["is_prepayment_eligible"], bool)
    assert isinstance(data["duration_years"], _NUM)
    assert data["duration_years"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_assumption_set(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert data["domain"] in ("PREPAYMENT", "DEPOSIT_DECAY", "DEPOSIT_BETA")
    assert isinstance(data["params"], dict)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED")
    assert isinstance(data["created_by_user_id"], str)
    assert data["governance_flag"] in ("NONE", "REVIEW_REQUIRED")
    assert "approved_by_user_id" in data
    assert "approved_at" in data


def assert_rate_scenario(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("PARALLEL_SHOCK", "RAMP", "REGULATORY_PRESET")
    assert data["horizon_months"] in (12, 24)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_simulation_run(data: dict):
    _assert_common_fields(data)
    for field in ("book_id", "scenario_id", "prepayment_set_id",
                  "decay_set_id", "beta_set_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must be a UUID"
    assert data["balance_sheet_convention"] in ("STATIC", "DYNAMIC")
    assert isinstance(data["book_version_pinned"], int)
    assert data["status"] in ("COMPLETED", "PUBLISHED")
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    for field in ("nii_base_cents", "nii_scenario_cents",
                  "eve_base_cents", "eve_scenario_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    for field in ("nii_delta_pct", "eve_delta_pct"):
        assert isinstance(data[field], _NUM), f"{field} must be numeric"
    assert data["breach_summary"] in ("NONE", "NII", "EVE", "BOTH")
    assert isinstance(data["assumption_stale"], bool)


def assert_policy_limit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert data["metric"] in ("NII_DELTA_PCT", "EVE_DELTA_PCT")
    kinds = data["applies_to_kinds"]
    assert kinds == "ALL" or (
        isinstance(kinds, list)
        and all(k in ("PARALLEL_SHOCK", "RAMP", "REGULATORY_PRESET") for k in kinds)
    )
    assert isinstance(data["threshold_pct"], _NUM) and data["threshold_pct"] > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_limit_breach(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert data["metric"] in ("NII_DELTA_PCT", "EVE_DELTA_PCT", "HEDGE_COVERAGE")
    assert data["status"] in (
        "OPEN", "ACKNOWLEDGED", "REMEDIATION_PLANNED", "ESCALATED", "CLOSED")
    assert isinstance(data["period_month"], str)
    assert len(data["period_month"]) == 7
    assert "run_id" in data and "limit_id" in data
    assert "observed_delta_pct" in data and "threshold_pct" in data
    assert "remediation_note" in data and "due_date" in data
    assert "resolution_note" in data


def assert_hedge_relationship(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert is_valid_uuid(data.get("position_id", "")), "position_id must be a UUID"
    assert data["instrument"] in ("PAYER_SWAP", "RECEIVER_SWAP", "CAP", "FLOOR")
    assert data["designation_type"] in ("FAIR_VALUE", "CASH_FLOW")
    assert isinstance(data["notional_cents"], int) and data["notional_cents"] > 0
    assert isinstance(data["fixed_rate_bps"], int) and data["fixed_rate_bps"] >= 0
    assert data["status"] in (
        "PROPOSED", "DESIGNATED", "ACTIVE", "DEDESIGNATED", "TERMINATED")


def assert_hedge_effectiveness_test(data: dict):
    # PRD §2.5: append-only event — carries id and created_at only.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "an append-only effectiveness test must not carry updated_at"
    assert "version" not in data, \
        "an append-only effectiveness test must not carry version"
    assert is_valid_uuid(data.get("hedge_id", "")), "hedge_id must be a UUID"
    assert isinstance(data["test_month"], str) and len(data["test_month"]) == 7
    assert data["method"] in ("DOLLAR_OFFSET", "REGRESSION")
    assert isinstance(data["hedge_value_change_cents"], int)
    assert isinstance(data["hedged_item_value_change_cents"], int)
    assert data["result"] in ("PASS", "FAIL")


def assert_backtest_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert is_valid_uuid(data.get("assumption_set_id", "")), \
        "assumption_set_id must be a UUID"
    assert data["domain"] in ("PREPAYMENT", "DEPOSIT_DECAY", "DEPOSIT_BETA")
    assert isinstance(data["start_month"], str) and len(data["start_month"]) == 7
    assert isinstance(data["observation_months"], int)
    assert data["observation_months"] > 0
    for field in ("observed_value_pct", "predicted_value_pct", "deviation_pct"):
        assert isinstance(data[field], _NUM), f"{field} must be numeric"
    assert data["outcome"] in ("WITHIN_TOLERANCE", "BREACH")
    assert data["status"] in ("OPEN", "CLOSED_ACCEPTED", "CLOSED_REVISED")


def assert_alco_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_id", "")), "book_id must be a UUID"
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED")
    assert isinstance(data["run_count"], int) and data["run_count"] >= 0
    assert isinstance(data["open_breach_count"], int)
    assert data["open_breach_count"] >= 0
    assert isinstance(data["regulatory_coverage_complete"], bool)
    assert "worst_nii_delta_pct" in data and "worst_eve_delta_pct" in data
    assert "submitted_by_user_id" in data and "acknowledged_by_user_id" in data


def assert_book_totals_consistent(book: dict):
    """Domain invariant: a book's balance aggregates are non-negative and its
    EVE base (assets minus liabilities) matches the stored totals."""
    assert book["total_assets_cents"] >= 0
    assert book["total_liabilities_cents"] >= 0
    assert book["hedged_notional_cents"] >= 0
