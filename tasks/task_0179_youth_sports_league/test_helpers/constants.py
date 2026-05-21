"""Domain thresholds — numeric constants from PRD.

Values mirror PRD §2.7 (rainout/field/referee), §2.8 (referee buffer +
weekly cap), §2.9 (volunteer hours), §2.10 (precision), §3.1 (season),
§3.3 (team / draft / tier-A), and §3.6 (playoffs).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Tier classification thresholds — PRD §2.10 / §3.2
# ---------------------------------------------------------------------------
TIER_A_MIN: float = 85.0
TIER_B_MIN: float = 70.0
TIER_C_MIN: float = 50.0


# ---------------------------------------------------------------------------
# Roster / draft constraints — PRD §3.1, §3.3
# ---------------------------------------------------------------------------
MIN_TEAMS_TO_START_REGULAR_SEASON: int = 4
MIN_ROSTER_TO_START_REGULAR_SEASON: int = 8
TIER_A_CAP: int = 3
DRAFT_POSITION_MIN: int = 1
DRAFT_POSITION_MAX: int = 32


# ---------------------------------------------------------------------------
# Game scheduling — PRD §2.7
# ---------------------------------------------------------------------------
GAME_DURATION_MINUTES: int = 90


# ---------------------------------------------------------------------------
# Referee buffer + weekly cap — PRD §2.8
# ---------------------------------------------------------------------------
REFEREE_BUFFER_MINUTES: int = 30
REFEREE_WEEKLY_CAP_DEFAULT: int = 5
REFEREE_WEEKLY_CAP_MIN: int = 1
REFEREE_WEEKLY_CAP_MAX: int = 20


# ---------------------------------------------------------------------------
# Rainout window — PRD §2.7 / §3.1
# ---------------------------------------------------------------------------
RAINOUT_WINDOW_DAYS_DEFAULT: int = 14
RAINOUT_WINDOW_DAYS_MIN: int = 1
RAINOUT_WINDOW_DAYS_MAX: int = 60


# ---------------------------------------------------------------------------
# Volunteer accounting — PRD §2.9
# ---------------------------------------------------------------------------
VOLUNTEER_HOURS_REQUIRED_DEFAULT: float = 6.0
VOLUNTEER_HOURS_REQUIRED_MIN: float = 0.0
VOLUNTEER_HOURS_REQUIRED_MAX: float = 100.0
VOLUNTEER_ON_TRACK_FRACTION: float = 0.5
VOLUNTEER_CHECK_IN_GRACE_MINUTES: int = 30


# ---------------------------------------------------------------------------
# Playoffs — PRD §3.6
# ---------------------------------------------------------------------------
PLAYOFF_BRACKET_SIZE: int = 4
PLAYOFF_ROUND_GAP_DAYS: int = 7


# ---------------------------------------------------------------------------
# Field string + season name length limits — PRD §3.1 / §3.4
# ---------------------------------------------------------------------------
SEASON_NAME_MIN_LEN: int = 1
SEASON_NAME_MAX_LEN: int = 120
TEAM_NAME_MIN_LEN: int = 1
TEAM_NAME_MAX_LEN: int = 80
PLAYER_NAME_MIN_LEN: int = 1
PLAYER_NAME_MAX_LEN: int = 80
GUARDIAN_NAME_MIN_LEN: int = 1
GUARDIAN_NAME_MAX_LEN: int = 160
FIELD_ID_MIN_LEN: int = 1
FIELD_ID_MAX_LEN: int = 40


# ---------------------------------------------------------------------------
# Test defaults — used by fixtures + factories.
# Clock starts WAY before any scheduled fixture activity.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "SEASON_REGULAR_START": "2026-05-01T00:00:00.000Z",
    "SEASON_REGULAR_END": "2026-07-31T23:59:59.999Z",
    "SEASON_PLAYOFF_CUTOFF": "2026-08-01T00:00:00.000Z",
    "SEASON_MIN_BIRTH_DATE": "2014-01-01T00:00:00.000Z",
    "SEASON_MAX_BIRTH_DATE": "2015-12-31T00:00:00.000Z",
    "PLAYER_DEFAULT_BIRTH_DATE": "2015-06-01T00:00:00.000Z",
    "BIRTH_CERT_URI": "https://docs.example.com/bc-test-default.pdf",
    "DEFAULT_PHONE": "+15555550100",
    "VOLUNTEER_HOURS_REQUIRED": 6.0,
    "RAINOUT_WINDOW_DAYS": 14,
    "REFEREE_WEEKLY_CAP": 5,
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TIER_A_MIN",
    "TIER_B_MIN",
    "TIER_C_MIN",
    "MIN_TEAMS_TO_START_REGULAR_SEASON",
    "MIN_ROSTER_TO_START_REGULAR_SEASON",
    "TIER_A_CAP",
    "DRAFT_POSITION_MIN",
    "DRAFT_POSITION_MAX",
    "GAME_DURATION_MINUTES",
    "REFEREE_BUFFER_MINUTES",
    "REFEREE_WEEKLY_CAP_DEFAULT",
    "REFEREE_WEEKLY_CAP_MIN",
    "REFEREE_WEEKLY_CAP_MAX",
    "RAINOUT_WINDOW_DAYS_DEFAULT",
    "RAINOUT_WINDOW_DAYS_MIN",
    "RAINOUT_WINDOW_DAYS_MAX",
    "VOLUNTEER_HOURS_REQUIRED_DEFAULT",
    "VOLUNTEER_HOURS_REQUIRED_MIN",
    "VOLUNTEER_HOURS_REQUIRED_MAX",
    "VOLUNTEER_ON_TRACK_FRACTION",
    "VOLUNTEER_CHECK_IN_GRACE_MINUTES",
    "PLAYOFF_BRACKET_SIZE",
    "PLAYOFF_ROUND_GAP_DAYS",
    "SEASON_NAME_MIN_LEN",
    "SEASON_NAME_MAX_LEN",
    "TEAM_NAME_MIN_LEN",
    "TEAM_NAME_MAX_LEN",
    "PLAYER_NAME_MIN_LEN",
    "PLAYER_NAME_MAX_LEN",
    "GUARDIAN_NAME_MIN_LEN",
    "GUARDIAN_NAME_MAX_LEN",
    "FIELD_ID_MIN_LEN",
    "FIELD_ID_MAX_LEN",
    "TEST_DEFAULTS",
]
