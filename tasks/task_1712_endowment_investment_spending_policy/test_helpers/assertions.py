"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_pool(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pool_name"], str) and data["pool_name"]
    assert isinstance(data["inception_fiscal_year"], int)
    assert data["pool_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["current_quarter_index"], int) and data["current_quarter_index"] >= 0
    assert isinstance(data["current_unit_price_millicents"], int)
    assert data["current_unit_price_millicents"] >= 1, "unit price is floored at 1 millicent"
    assert isinstance(data["total_units_outstanding_micro"], int)
    assert isinstance(data["total_market_value_cents"], int)


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pool_id", ""))
    assert 100 <= data["spending_rate_bps"] <= 2000
    assert 4 <= data["smoothing_window_quarters"] <= 20
    assert 0 <= data["band_floor_bps"] <= 10000
    assert 0 <= data["band_cap_bps"] <= 10000
    assert isinstance(data["effective_from_fiscal_year"], int)
    assert data["policy_status"] in ("DRAFT", "ADOPTED", "SUPERSEDED", "WITHDRAWN")
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_valuation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pool_id", ""))
    assert isinstance(data["quarter_index"], int) and data["quarter_index"] >= 1
    assert data["valuation_status"] in ("PRELIMINARY", "FINAL", "SUPERSEDED")
    assert isinstance(data["estimated_pool_market_value_cents"], int)
    assert data["estimated_pool_market_value_cents"] >= 0
    assert isinstance(data["preliminary_unit_price_millicents"], int)


def assert_donor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["donor_name"], str) and data["donor_name"]
    assert data["donor_type"] in ("INDIVIDUAL", "FOUNDATION", "CORPORATION", "ESTATE")
    assert isinstance(data["total_contributed_cents"], int)
    assert data["total_contributed_cents"] >= 0


def assert_fund(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pool_id", ""))
    assert isinstance(data["fund_code"], str) and data["fund_code"]
    assert data["endowment_class"] in ("TRUE_ENDOWMENT", "QUASI_ENDOWMENT", "TERM_ENDOWMENT")
    assert data["purpose_restriction"] in (
        "UNRESTRICTED", "SCHOLARSHIP", "PROFESSORSHIP", "RESEARCH", "CAPITAL_PROJECTS",
    )
    assert data["fund_status"] in ("DRAFT", "ACTIVE", "TERMINATED")
    assert data["spending_posture"] in ("NORMAL", "SPENDING_SUSPENDED", "EXCEPTION_ACTIVE")
    assert isinstance(data["historic_gift_value_cents"], int)
    assert isinstance(data["pledged_corpus_cents"], int)
    assert isinstance(data["units_held_micro"], int) and data["units_held_micro"] >= 0
    assert isinstance(data["market_value_cents"], int) and data["market_value_cents"] >= 0
    assert isinstance(data["is_underwater"], bool)


def assert_gift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fund_id", ""))
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert data["gift_type"] in ("CORPUS", "EXPENDABLE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["gift_status"] in ("PLEDGED", "RECEIVED", "UNITIZED", "RETURNED", "CANCELLED")


def assert_distribution(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fund_id", ""))
    assert isinstance(data["fiscal_year"], int)
    assert data["distribution_status"] in (
        "PROJECTED", "PROPOSED", "REVISION_REQUESTED", "APPROVED", "DISTRIBUTED", "CANCELLED",
    )
    assert isinstance(data["smoothed_base_cents"], int)
    assert isinstance(data["raw_amount_cents"], int)
    assert isinstance(data["band_adjusted_amount_cents"], int)
    assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["distributed_amount_cents"], int)


def assert_exception(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fund_id", ""))
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert data["exception_status"] in (
        "REQUESTED", "ENDORSED", "APPROVED", "REJECTED", "EXERCISED", "EXPIRED", "RESCINDED",
    )
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]


def assert_payout(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("distribution_id", ""))
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["program_purpose"] in ("SCHOLARSHIP", "PROFESSORSHIP", "RESEARCH", "CAPITAL_PROJECTS")
    assert isinstance(data["allocated_amount_cents"], int) and data["allocated_amount_cents"] > 0
    assert data["payout_status"] in ("SCHEDULED", "DISBURSED", "CLOSED_FULLY_SPENT", "CLOSED_RETURNED")
    assert isinstance(data["spent_amount_cents"], int)
    assert isinstance(data["unspent_amount_cents"], int)


def assert_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pool_id", ""))
    assert data["asset_class"] in (
        "US_EQUITY", "DEVELOPED_INTL_EQUITY", "EMERGING_MARKETS", "FIXED_INCOME",
        "REAL_ASSETS", "PRIVATE_EQUITY", "CASH",
    )
    assert 0 <= data["target_pct_bps"] <= 10000
    assert 1 <= data["rebalance_band_bps"] <= 5000
    assert isinstance(data["actual_pct_bps"], int)
    assert data["drift_status"] in ("IN_BAND", "BREACHED")
    assert isinstance(data["drift_acknowledged"], bool)


def assert_manager(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pool_id", ""))
    assert isinstance(data["manager_name"], str) and data["manager_name"]
    assert isinstance(data["benchmark_code"], str) and data["benchmark_code"]
    assert isinstance(data["coverage_start_quarter"], int) and data["coverage_start_quarter"] >= 1
    assert data["engagement_status"] in (
        "PROSPECT", "ENGAGED", "WATCHLIST", "PROBATION", "TERMINATED", "DECLINED",
    )
    assert isinstance(data["neg_excess_streak"], int) and data["neg_excess_streak"] >= 0
    assert isinstance(data["nonneg_excess_streak"], int) and data["nonneg_excess_streak"] >= 0


def assert_manager_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("manager_id", ""))
    assert isinstance(data["quarter_index"], int) and data["quarter_index"] >= 1
    assert isinstance(data["beginning_mv_cents"], int) and data["beginning_mv_cents"] >= 0
    assert isinstance(data["ending_mv_cents"], int) and data["ending_mv_cents"] >= 0
    assert isinstance(data["flows"], list)
    assert isinstance(data["benchmark_return_bps"], int)
    assert isinstance(data["return_bps"], int)
    assert isinstance(data["simple_return_bps"], int)
    assert isinstance(data["excess_bps"], int)
    assert data["excess_bps"] == data["return_bps"] - data["benchmark_return_bps"], (
        "excess_bps must equal return_bps minus benchmark_return_bps"
    )


def assert_annual_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pool_id", ""))
    assert data["report_type"] in ("DONOR_FUND", "BOARD_INVESTMENT", "SPENDING_COMPLIANCE")
    assert isinstance(data["fiscal_year"], int)
    assert data["report_status"] in ("DRAFT", "UNDER_REVIEW", "PUBLISHED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_ledger_entry(data: dict):
    """Append-only log row (PRD §2.4): id and created_at only; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "UnitLedgerEntry must not carry updated_at"
    assert "version" not in data, "UnitLedgerEntry must not carry version"
    assert is_valid_uuid(data.get("fund_id", ""))
    assert isinstance(data["quarter_index"], int) and data["quarter_index"] >= 1
    assert data["entry_type"] in (
        "GIFT_UNITIZE", "REINVEST_UNITIZE", "DISTRIBUTION_REDEEM", "CORPUS_REDEEM",
    )
    assert isinstance(data["units_delta_micro"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reference_id"], str) and data["reference_id"]


def assert_fund_invariants(data: dict):
    """Fund-level invariants from PRD §3.1 and §3.4 step 5."""
    assert data["historic_gift_value_cents"] >= 0, "HGV is floored at 0"
    assert data["units_held_micro"] >= 0
    assert data["market_value_cents"] >= 0
    assert data["is_underwater"] == (
        data["market_value_cents"] < data["historic_gift_value_cents"]
    ), "is_underwater must equal (market_value_cents < historic_gift_value_cents)"


def assert_pool_unit_identity(pool: dict, funds: list):
    """PRD §2.5: total_units_outstanding_micro is the exact integer sum of funds' units."""
    total = sum(f["units_held_micro"] for f in funds)
    assert pool["total_units_outstanding_micro"] == total, (
        f"pool total {pool['total_units_outstanding_micro']} != sum of fund units {total}"
    )
