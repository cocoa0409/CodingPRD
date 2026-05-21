"""Entity assertions and domain invariant checkers.

`assert_{entity}(data)` walks the field set the PRD declares for each
entity. Primary resources (PRD §2.4) carry id + created_at +
updated_at + version. AuditEvent is the only append-only record and
carries only id + created_at.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status enum-like sets.
# ---------------------------------------------------------------------------
SEASON_STATUSES = {"DRAFT_OPEN", "REGULAR_SEASON", "PLAYOFFS", "CLOSED"}
AGE_DIVISIONS = {"TBALL", "MINORS", "MAJORS", "INTERMEDIATE", "JUNIORS"}
PLAYER_STATUSES = {
    "PENDING_VERIFICATION", "AGE_VERIFIED", "EVALUATED",
    "DRAFTED", "WITHDRAWN",
}
EVALUATION_TIERS = {"TIER_A", "TIER_B", "TIER_C", "TIER_D"}
VOLUNTEER_STATUSES = {"DEFICIENT", "ON_TRACK", "FULFILLED"}
GAME_STATUSES = {
    "SCHEDULED", "POSTPONED", "RESCHEDULED",
    "COMPLETED", "FORFEITED", "CANCELLED",
}
GAME_TYPES = {"REGULAR", "PLAYOFF"}
PLAYOFF_STATUSES = {"NOT_QUALIFIED", "QUALIFIED", "ELIMINATED", "CHAMPION"}
SHIFT_STATUSES = {
    "SCHEDULED", "CHECKED_IN", "APPROVED", "NO_SHOW", "CANCELLED",
}
SHIFT_ROLES = {
    "SCOREKEEPER", "CONCESSIONS", "FIELD_PREP",
    "UMPIRE_ASSIST", "SETUP_TEARDOWN",
}
CERTIFICATION_LEVELS = {"LEVEL_1", "LEVEL_2", "LEVEL_3"}


# ---------------------------------------------------------------------------
# Envelope checks — primary vs append-only.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Every persisted resource carries a server-minted `id`
    formatted as a UUID with no type prefix. Most resources also carry
    the audit trio `created_at`, `updated_at`, and `version`, where the
    two timestamps are ISO 8601 UTC strings with three fractional digits
    and `version` is an integer that starts at 1 on creation and is
    incremented by exactly one on every mutation."
    """
    assert "id" in data, f"primary row missing 'id': {data}"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "The audit-trail records of the league — the
    `AuditEvent` rows — are an exception: they carry only `id` and
    `created_at`, with no `updated_at` and no `version`, because they
    are append-only and never re-edited."
    """
    assert "id" in data, f"append-only row missing 'id': {data}"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "AuditEvent must not expose 'updated_at' "
        f"(found {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "AuditEvent must not expose 'version' "
        f"(found {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.4: "version is an integer that starts at 1 on creation
    and is incremented by exactly one on every mutation."
    """
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Season — PRD §3.1
# ---------------------------------------------------------------------------
def assert_season(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("name"), str), "name must be string"
    assert data.get("age_division") in AGE_DIVISIONS, (
        f"age_division must be in {AGE_DIVISIONS}, "
        f"got {data.get('age_division')!r}"
    )
    assert data.get("status") in SEASON_STATUSES, (
        f"Season.status must be in {SEASON_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    for ts in ("min_birth_date", "max_birth_date",
               "regular_season_start", "regular_season_end",
               "playoff_cutoff_date"):
        assert ts in data, f"missing '{ts}'"
        assert is_iso8601_timestamp(str(data[ts])), (
            f"{ts} must be ISO 8601, got {data[ts]!r}"
        )
    assert isinstance(data.get("rainout_window_days"), int)
    assert 1 <= data["rainout_window_days"] <= 60
    vh = data.get("volunteer_hours_required_per_family")
    assert isinstance(vh, (int, float))
    assert 0 <= float(vh) <= 100


# ---------------------------------------------------------------------------
# Player — PRD §3.2
# ---------------------------------------------------------------------------
def assert_player(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    for fk in ("season_id", "guardian_id"):
        assert fk in data, f"missing '{fk}'"
        assert isinstance(data[fk], str) and data[fk], (
            f"{fk} must be non-empty string"
        )
    assert isinstance(data.get("first_name"), str)
    assert isinstance(data.get("last_name"), str)
    assert is_iso8601_timestamp(str(data.get("birth_date", ""))), (
        f"birth_date must be ISO 8601, got {data.get('birth_date')!r}"
    )
    assert data.get("status") in PLAYER_STATUSES, (
        f"Player.status must be in {PLAYER_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    tier = data.get("evaluation_tier")
    assert tier is None or tier in EVALUATION_TIERS, (
        f"evaluation_tier must be null or in {EVALUATION_TIERS}, "
        f"got {tier!r}"
    )


# ---------------------------------------------------------------------------
# Guardian — PRD §3.2
# ---------------------------------------------------------------------------
def assert_guardian(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("phone"), str)
    vh = data.get("volunteer_hours_logged")
    assert isinstance(vh, (int, float))
    assert float(vh) >= 0
    assert data.get("volunteer_status") in VOLUNTEER_STATUSES, (
        f"Guardian.volunteer_status must be in {VOLUNTEER_STATUSES}, "
        f"got {data.get('volunteer_status')!r}"
    )


# ---------------------------------------------------------------------------
# Coach — PRD §3.3
# ---------------------------------------------------------------------------
def assert_coach(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("background_check_passed"), bool)


# ---------------------------------------------------------------------------
# Referee — PRD §2.8
# ---------------------------------------------------------------------------
def assert_referee(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert data.get("certification_level") in CERTIFICATION_LEVELS, (
        f"certification_level must be in {CERTIFICATION_LEVELS}, "
        f"got {data.get('certification_level')!r}"
    )
    cap = data.get("weekly_assignment_cap")
    assert isinstance(cap, int) and 1 <= cap <= 20
    assert isinstance(data.get("active"), bool)


# ---------------------------------------------------------------------------
# Team — PRD §3.3, §3.5, §3.6
# ---------------------------------------------------------------------------
def assert_team(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("season_id"), str) and data["season_id"]
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("head_coach_id"), str) and data["head_coach_id"]
    dp = data.get("draft_position")
    assert isinstance(dp, int) and 1 <= dp <= 32
    assert isinstance(data.get("roster_count"), int)
    assert data["roster_count"] >= 0
    assert isinstance(data.get("tier_a_count"), int)
    assert data["tier_a_count"] >= 0
    assert isinstance(data.get("wins"), int) and data["wins"] >= 0
    assert isinstance(data.get("losses"), int) and data["losses"] >= 0
    seed = data.get("playoff_seed")
    assert seed is None or (isinstance(seed, int) and seed >= 1)
    assert data.get("playoff_status") in PLAYOFF_STATUSES, (
        f"Team.playoff_status must be in {PLAYOFF_STATUSES}, "
        f"got {data.get('playoff_status')!r}"
    )


# ---------------------------------------------------------------------------
# Game — PRD §3.4
# ---------------------------------------------------------------------------
def assert_game(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    for fk in ("season_id", "home_team_id", "away_team_id"):
        assert isinstance(data.get(fk), str) and data[fk]
    assert data.get("home_team_id") != data.get("away_team_id"), (
        "Game home_team_id must differ from away_team_id"
    )
    assert data.get("game_type") in GAME_TYPES, (
        f"game_type must be in {GAME_TYPES}, got {data.get('game_type')!r}"
    )
    assert isinstance(data.get("field_id"), str) and data["field_id"]
    for ts in ("scheduled_start", "scheduled_end",
               "original_scheduled_start"):
        assert ts in data and is_iso8601_timestamp(str(data[ts])), (
            f"{ts} must be ISO 8601, got {data.get(ts)!r}"
        )
    assert data.get("status") in GAME_STATUSES, (
        f"Game.status must be in {GAME_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# VolunteerShift — PRD §3.7
# ---------------------------------------------------------------------------
def assert_volunteer_shift(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    for fk in ("season_id", "guardian_id"):
        assert isinstance(data.get(fk), str) and data[fk]
    assert data.get("role") in SHIFT_ROLES, (
        f"shift.role must be in {SHIFT_ROLES}, got {data.get('role')!r}"
    )
    for ts in ("scheduled_start", "scheduled_end"):
        assert ts in data and is_iso8601_timestamp(str(data[ts])), (
            f"{ts} must be ISO 8601, got {data.get(ts)!r}"
        )
    assert data.get("status") in SHIFT_STATUSES, (
        f"shift.status must be in {SHIFT_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    hours = data.get("hours_credited", 0)
    assert isinstance(hours, (int, float)) and float(hours) >= 0


# ---------------------------------------------------------------------------
# AuditEvent — PRD §3.8
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    for f in ("entity_type", "entity_id", "actor_role", "actor_id", "action"):
        assert f in data, f"AuditEvent missing '{f}'"


# ---------------------------------------------------------------------------
# Domain invariant helpers.
# ---------------------------------------------------------------------------
def assert_hours_precision(value: float) -> None:
    """PRD §2.9 / §3.7: hours_credited and volunteer_hours_logged are
    expressed to two decimal places (half-up)."""
    # We accept either int or float; both must round-trip at 2 decimals.
    rounded = round(float(value) + 1e-9, 2)
    assert abs(rounded - float(value)) < 1e-6, (
        f"Hours value {value!r} not at 2-decimal precision"
    )


def assert_team_games_played_invariant(team: Dict[str, Any],
                                       expected_terminal_count: int) -> None:
    """PRD §3.5 conserved quantity: team.wins + team.losses equals the
    count of terminal (COMPLETED or FORFEITED) games involving the team.
    CANCELLED games contribute zero to both totals."""
    actual = team["wins"] + team["losses"]
    assert actual == expected_terminal_count, (
        f"Team.wins ({team['wins']}) + Team.losses ({team['losses']}) "
        f"= {actual}, expected {expected_terminal_count}"
    )


__all__ = [
    # status sets
    "SEASON_STATUSES",
    "AGE_DIVISIONS",
    "PLAYER_STATUSES",
    "EVALUATION_TIERS",
    "VOLUNTEER_STATUSES",
    "GAME_STATUSES",
    "GAME_TYPES",
    "PLAYOFF_STATUSES",
    "SHIFT_STATUSES",
    "SHIFT_ROLES",
    "CERTIFICATION_LEVELS",
    # envelope
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    # entity
    "assert_season",
    "assert_player",
    "assert_guardian",
    "assert_coach",
    "assert_referee",
    "assert_team",
    "assert_game",
    "assert_volunteer_shift",
    "assert_audit_event",
    # invariants
    "assert_hours_precision",
    "assert_team_games_played_invariant",
]
