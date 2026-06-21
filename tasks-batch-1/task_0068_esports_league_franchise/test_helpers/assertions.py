"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_season(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["salary_cap_cents"], int) and data["salary_cap_cents"] >= 1
    assert data["phase"] in ["SETUP", "REGULAR", "PLAYOFFS", "COMPLETE"]
    assert data["trade_window_state"] in ["OPEN", "CLOSED"]
    assert isinstance(data.get("version"), int)


def assert_team(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["market_size_weight"], int) and data["market_size_weight"] >= 1
    assert isinstance(data["payroll_active_cents"], int) and data["payroll_active_cents"] >= 0
    assert isinstance(data["penalty_points"], int) and data["penalty_points"] >= 0
    assert data["posture"] in ["OPEN", "RESTRICTED"]
    assert isinstance(data["eliminated"], bool)
    assert isinstance(data.get("version"), int)


def assert_player(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["handle"], str) and len(data["handle"]) > 0
    assert data["status"] in ["FREE_AGENT", "SIGNED"]
    assert isinstance(data.get("version"), int)


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be valid UUID"
    assert is_valid_uuid(data.get("player_id", "")), "player_id must be valid UUID"
    assert isinstance(data["base_salary_cents"], int) and data["base_salary_cents"] >= 1
    assert data["contract_type"] in ["STANDARD", "TWO_WAY"]
    assert isinstance(data["two_way_promoted"], bool)
    assert data["status"] in ["ACTIVE", "WAIVED"]
    assert isinstance(data.get("version"), int)


def assert_stint(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be valid UUID"
    assert is_valid_uuid(data.get("player_id", "")), "player_id must be valid UUID"


def assert_trade(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("from_team_id", "")), "from_team_id must be valid UUID"
    assert is_valid_uuid(data.get("to_team_id", "")), "to_team_id must be valid UUID"
    assert isinstance(data["contract_ids_out"], list)
    assert isinstance(data["contract_ids_in"], list)
    assert data["status"] in ["PROPOSED", "ACCEPTED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data.get("version"), int)


def assert_fine(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be valid UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["penalty_points"], int) and data["penalty_points"] >= 1
    assert data["status"] in ["ASSESSED", "WAIVED"]
    assert isinstance(data.get("version"), int)


def assert_sponsorship(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["sponsor_name"], str) and len(data["sponsor_name"]) > 0
    assert isinstance(data["pool_cents"], int) and data["pool_cents"] >= 1
    assert 0 <= data["league_share_pct"] < 1
    assert data["status"] in ["PENDING", "DISTRIBUTED"]
    assert isinstance(data.get("version"), int)


def assert_revenue_share(data: dict):
    """RevenueShare is an immutable audit record: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be valid UUID"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["weight_used"], int)
