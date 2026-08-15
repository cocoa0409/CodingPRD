"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DEAL_STATUSES = ["DRAFT", "UNDERWRITING", "IC_REVIEW", "APPROVED", "REJECTED", "DEAD"]
SCENARIO_STATUSES = ["DRAFT", "COMPUTED", "SUPERSEDED"]
MEMO_STATUSES = ["DRAFT", "SUBMITTED", "UNDER_VOTE", "APPROVED", "REJECTED"]
STRATEGIES = ["CORE", "CORE_PLUS", "VALUE_ADD", "OPPORTUNISTIC"]
PROPERTY_TYPES = ["MULTIFAMILY", "OFFICE", "RETAIL", "INDUSTRIAL", "MIXED_USE"]
EXPENSE_CATEGORIES = [
    "TAXES", "INSURANCE", "UTILITIES", "REPAIRS",
    "MANAGEMENT", "PAYROLL", "MARKETING", "OTHER",
]
SCENARIO_KINDS = ["BASE", "DOWNSIDE", "UPSIDE", "STRESS"]
SIZING_CONSTRAINTS = ["DSCR", "LTV", "BOTH"]
VOTE_VALUES = ["YES", "NO", "ABSTAIN"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_deal(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deal_code"], str) and 4 <= len(data["deal_code"]) <= 32
    assert isinstance(data["deal_name"], str)
    assert data["strategy"] in STRATEGIES
    assert data["status"] in DEAL_STATUSES
    assert isinstance(data["target_purchase_price_cents"], int)
    assert isinstance(data["analyst_id"], str) and data["analyst_id"]


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deal_id"], str)
    assert data["property_type"] in PROPERTY_TYPES
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["rentable_sqft"], int) and data["rentable_sqft"] >= 100
    assert isinstance(data["year_built"], int) and 1800 <= data["year_built"] <= 2100
    occ = data.get("occupancy_pct")
    assert occ is None or (isinstance(occ, (int, float)) and 0 <= occ <= 100)


def assert_rent_roll_period(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["occupied_units"], int) and data["occupied_units"] >= 0
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["gross_potential_rent_cents"], int)
    assert isinstance(data["collected_rent_cents"], int)
    assert isinstance(data["concessions_cents"], int) and data["concessions_cents"] >= 0
    assert isinstance(data["source_doc_ref"], str)


def assert_operating_expense(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["period_year"], int)
    assert data["category"] in EXPENSE_CATEGORIES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["is_recoverable"], bool)


def assert_market_assumption(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["market_rent_growth_yr1_bps"], int)
    assert isinstance(data["market_rent_growth_steady_bps"], int)
    assert isinstance(data["expense_growth_bps"], int)
    assert isinstance(data["exit_cap_rate_bps"], int) and data["exit_cap_rate_bps"] > 0
    assert isinstance(data["hold_period_years"], int) and 1 <= data["hold_period_years"] <= 15
    assert isinstance(data["capex_per_unit_cents"], int) and data["capex_per_unit_cents"] >= 0
    assert isinstance(data["lease_up_months"], int) and 0 <= data["lease_up_months"] <= 36
    assert isinstance(data["is_active"], bool)


def assert_scenario(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deal_id"], str)
    assert data["scenario_kind"] in SCENARIO_KINDS
    assert isinstance(data["assumption_id"], str)
    assert isinstance(data["occupancy_stress_pct"], int) and 0 <= data["occupancy_stress_pct"] <= 100
    assert data["status"] in SCENARIO_STATUSES


def assert_debt_sizing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["scenario_id"], str)
    assert isinstance(data["loan_amount_cents"], int) and data["loan_amount_cents"] >= 0
    assert isinstance(data["interest_rate_bps"], int)
    assert isinstance(data["amortization_years"], int) and 1 <= data["amortization_years"] <= 30
    assert isinstance(data["io_months"], int) and 0 <= data["io_months"] <= 120
    assert isinstance(data["min_dscr_pct"], int)
    assert isinstance(data["max_ltv_pct"], int)
    assert isinstance(data["dscr_at_size_pct"], int)
    assert isinstance(data["ltv_at_size_pct"], int)
    assert data["sizing_constraint"] in SIZING_CONSTRAINTS


def assert_waterfall(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["scenario_id"], str)
    assert isinstance(data["pref_return_bps"], int)
    assert isinstance(data["promote_tier1_bps"], int)
    assert isinstance(data["tier1_hurdle_bps"], int)
    assert isinstance(data["promote_tier2_bps"], int)
    assert isinstance(data["lp_split_cents"], int) and data["lp_split_cents"] >= 0
    assert isinstance(data["gp_split_cents"], int) and data["gp_split_cents"] >= 0
    assert isinstance(data["gp_promote_cents"], int) and data["gp_promote_cents"] >= 0


def assert_ic_memo(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["scenario_id"], str)
    assert data["recommendation"] in ["PURSUE", "PASS", "RENEGOTIATE"]
    assert isinstance(data["thesis"], str)
    assert isinstance(data["risks"], str)
    assert data["status"] in MEMO_STATUSES


def assert_ic_vote(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["memo_id"], str)
    assert isinstance(data["voter_user_id"], str) and data["voter_user_id"]
    assert data["vote"] in VOTE_VALUES
    assert is_iso8601_timestamp(data.get("cast_at", "")), "cast_at must be ISO 8601"


def assert_exactly_one_assumption_active(assumptions: list):
    """Exactly one assumption set per deal is active at any moment (PRD §3.3)."""
    actives = [a for a in assumptions if a.get("is_active") is True]
    assert len(actives) == 1, f"expected exactly one active assumption, got {len(actives)}"
