"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive int"


def assert_league(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SETUP", "REGISTRATION", "EVALUATION", "DRAFT", "SEASON",
        "PLAYOFFS", "CLOSED",
    ], f"unexpected league status {data.get('status')}"
    assert isinstance(data["total_registered_players"], int)
    assert isinstance(data["draft_round_index"], int)


def assert_division(data: dict):
    _assert_common(data)
    assert isinstance(data["min_league_age"], int)
    assert isinstance(data["max_league_age"], int)
    assert isinstance(data["roster_cap"], int)


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["volunteer_deposit_cents"], int)
    assert isinstance(data["volunteer_credit_cents"], int)
    # By construction credit never exceeds the deposit (PRD §3.2, §3.8).
    assert data["volunteer_credit_cents"] <= data["volunteer_deposit_cents"], \
        "volunteer_credit_cents must never exceed volunteer_deposit_cents"


def assert_player(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "REGISTERED", "AGE_VERIFIED", "EVALUATED", "DRAFTED",
        "ROSTERED", "WITHDRAWN",
    ], f"unexpected player status {data.get('status')}"
    assert isinstance(data["league_age"], int)


def assert_team(data: dict):
    _assert_common(data)
    assert isinstance(data["roster_count"], int)
    assert isinstance(data["wins"], int)
    assert isinstance(data["losses"], int)
    assert isinstance(data["run_differential"], int)


def assert_draft_pick(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "VOIDED"]
    assert isinstance(data["round_number"], int)
    assert isinstance(data["overall_number"], int)


def assert_field(data: dict):
    _assert_common(data)
    assert isinstance(data["turnover_buffer_minutes"], int)


def assert_referee(data: dict):
    _assert_common(data)
    assert isinstance(data["max_games_per_day"], int)


def assert_game(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "IN_PROGRESS", "FINAL", "RAINED_OUT", "FORFEITED",
    ], f"unexpected game status {data.get('status')}"
    assert isinstance(data["rainout_count"], int)


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PROPOSED", "CONFIRMED", "CHECKED_IN", "DECLINED", "RELEASED",
    ], f"unexpected assignment status {data.get('status')}"


def assert_volunteer_commitment(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLEDGED", "FULFILLED", "NO_SHOW"]
    assert isinstance(data["credit_cents"], int)
