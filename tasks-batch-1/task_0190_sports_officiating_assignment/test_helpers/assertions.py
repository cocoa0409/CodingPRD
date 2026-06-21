"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Append-only entities (ConflictDeclaration, Evaluation) carry only
id + created_at — their assertions deliberately do NOT require updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_league(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["sport"] in ["BASKETBALL", "SOCCER", "HOCKEY", "FOOTBALL"]
    assert isinstance(data["base_game_fee_cents"], int) and data["base_game_fee_cents"] >= 0
    assert isinstance(data["mileage_rate_cents_per_mile"], int)
    assert data["mileage_rate_cents_per_mile"] >= 0
    assert data["status"] in ["SETUP", "OPEN", "POSTSEASON", "ARCHIVED"]


def assert_official(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["rank"] in ["ROOKIE", "CERTIFIED", "SENIOR", "MASTER"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["games_worked_count"], int) and data["games_worked_count"] >= 0
    assert isinstance(data["noshow_count"], int) and data["noshow_count"] >= 0
    assert isinstance(data["penalty_points"], int)
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100, "reliability_score floored at 0, capped at 100"
    assert isinstance(data["postseason_eligible"], bool)


def assert_game(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "OPEN", "STAFFED", "LOCKED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["required_crew_size"], int) and data["required_crew_size"] >= 1
    assert isinstance(data["crew_filled_count"], int) and data["crew_filled_count"] >= 0
    assert isinstance(data["settlement_total_cents"], int)
    assert isinstance(data["is_postseason"], bool)


def assert_crew_slot(data: dict):
    _assert_common(data)
    assert data["position"] in ["REFEREE", "ASSISTANT", "OBSERVER"]
    assert data["status"] in ["VACANT", "OFFERED", "FILLED", "RELEASED"]


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "OFFERED", "ACCEPTED", "DECLINED", "CANCELLED", "COMPLETED", "NO_SHOW"
    ]
    assert isinstance(data["distance_miles"], (int, float))
    assert isinstance(data["provisional_pay_cents"], int)
    assert isinstance(data["final_pay_cents"], int)
    assert isinstance(data["mileage_cents"], int)
    assert isinstance(data["penalty_assessed_points"], int)


def assert_availability(data: dict):
    _assert_common(data)
    assert data["kind"] in ["AVAILABLE", "BLACKOUT"]
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]


def assert_season_ledger(data: dict):
    _assert_common(data)
    assert isinstance(data["penalty_points"], int)
    assert isinstance(data["total_pay_accrued_cents"], int)
    assert isinstance(data["total_mileage_accrued_cents"], int)


def assert_penalty_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "UPHELD", "DENIED"]
    assert isinstance(data["reversed_points"], int)


def assert_conflict_declaration(data: dict):
    _assert_append_only(data)
    assert data["scope"] in ["TEAM", "OFFICIAL"]
    assert "version" not in data, "ConflictDeclaration is immutable; no version field"


def assert_evaluation(data: dict):
    _assert_append_only(data)
    assert isinstance(data["score"], (int, float))
    assert 1.0 <= data["score"] <= 5.0
    assert "version" not in data, "Evaluation is immutable; no version field"


def assert_reliability_score_invariant(official: dict):
    """reliability_score == max(0, 100 - penalty_points) (§3.7)."""
    expected = max(0, 100 - official["penalty_points"])
    assert official["reliability_score"] == expected, (
        f"reliability_score should be max(0, 100 - {official['penalty_points']}) "
        f"= {expected}, got {official['reliability_score']}"
    )
