"""Payload factories — valid-by-default request bodies with keyword overrides."""

from typing import Any, Dict, List, Optional

from .constants import (
    AGE_18_OVER,
    FORMAT_MENS_DOUBLES,
    GENDER_M,
    RATING_SOURCE_COMPUTER,
    SIDE_HOME,
    STAGE_REGULAR,
    STRIKE_NO_SHOW_DEFAULT,
    SUBJECT_RATING_APPEAL,
    TIER_SECTION,
    VOTE_SUPPORT,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return base


def section_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "code": "SOCAL-2026",
            "name": "Southern California Section",
            "season_year": 2026,
        },
        overrides,
    )


def facility_payload(section_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "section_id": section_id,
            "name": "Balboa Courts",
            "court_count": 3,
            "turnaround_buffer_minutes": 30,
        },
        overrides,
    )


def league_payload(section_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "section_id": section_id,
            "parent_league_id": None,
            "tier": TIER_SECTION,
            "ntrp_level": 4.0,
            "age_group": AGE_18_OVER,
            "format": FORMAT_MENS_DOUBLES,
            "lines_per_match": 3,
            "min_active_roster_size": 2,
            "max_teams": 8,
            "match_duration_minutes": 180,
            "registration_opens_at": "2026-08-01T00:00:00Z",
            "registration_closes_at": "2026-08-08T00:00:00Z",
            "roster_lock_at": "2026-08-08T00:00:00Z",
            "season_end_at": "2026-10-31T00:00:00Z",
        },
        overrides,
    )


def player_payload(section_id: str, full_name: str = "Alex Rivera", **overrides):
    return _merge(
        {
            "section_id": section_id,
            "full_name": full_name,
            "birth_year": 1990,
            "gender": GENDER_M,
        },
        overrides,
    )


def rating_payload(level: float, source: str = RATING_SOURCE_COMPUTER, **overrides):
    return _merge({"source": source, "level": level}, overrides)


def team_payload(league_id: str, facility_id: str, name: str = "Balboa Aces", **overrides):
    return _merge(
        {"league_id": league_id, "name": name, "home_facility_id": facility_id},
        overrides,
    )


def roster_spot_payload(
    team_id: str, player_id: str, expected_team_version: int, **overrides
):
    return _merge(
        {
            "team_id": team_id,
            "player_id": player_id,
            "expected_team_version": expected_team_version,
        },
        overrides,
    )


def match_payload(
    league_id: str,
    home_team_id: str,
    away_team_id: str,
    round_number: int = 1,
    stage: str = STAGE_REGULAR,
    **overrides,
):
    return _merge(
        {
            "league_id": league_id,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "stage": stage,
            "round_number": round_number,
        },
        overrides,
    )


def schedule_payload(
    facility_id: str,
    scheduled_start_at: str,
    expected_match_version: int,
    courts_required: int = 3,
    **overrides,
):
    return _merge(
        {
            "facility_id": facility_id,
            "scheduled_start_at": scheduled_start_at,
            "courts_required": courts_required,
            "expected_match_version": expected_match_version,
        },
        overrides,
    )


def default_payload(
    defaulting_side: str = SIDE_HOME, default_kind: str = "NO_SHOW", **overrides
):
    return _merge(
        {
            "defaulting_side": defaulting_side,
            "default_kind": default_kind,
            "note": "Team never appeared",
        },
        overrides,
    )


def set_score(home_games: int, away_games: int) -> Dict[str, int]:
    return {"home_games": home_games, "away_games": away_games}


def scorecard_line(
    line_number: int,
    home_player_ids: List[str],
    away_player_ids: List[str],
    set_scores: Optional[List[Dict[str, int]]] = None,
    default_side: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "line_number": line_number,
        "home_player_ids": home_player_ids,
        "away_player_ids": away_player_ids,
        "set_scores": set_scores if set_scores is not None else [],
        "default_side": default_side,
    }


def scorecard_payload(match_id: str, lines: List[Dict[str, Any]], **overrides):
    return _merge({"match_id": match_id, "lines": lines}, overrides)


def strike_payload(player_id: str, kind: str = STRIKE_NO_SHOW_DEFAULT, **overrides):
    return _merge(
        {"player_id": player_id, "kind": kind, "reason": "Rule violation recorded"},
        overrides,
    )


def appeal_payload(player_id: str, direction: str, requested_level: float, **overrides):
    return _merge(
        {
            "player_id": player_id,
            "direction": direction,
            "requested_level": requested_level,
            "reason": "Competitive results support a different level",
        },
        overrides,
    )


def vote_payload(
    subject_id: str,
    vote: str = VOTE_SUPPORT,
    subject_type: str = SUBJECT_RATING_APPEAL,
    **overrides,
):
    return _merge(
        {"subject_type": subject_type, "subject_id": subject_id, "vote": vote},
        overrides,
    )


def grievance_payload(league_id: str, against_team_id: str, kind: str, **overrides):
    return _merge(
        {
            "league_id": league_id,
            "against_team_id": against_team_id,
            "kind": kind,
            "statement": "The opposing team broke a competition rule in this fixture",
        },
        overrides,
    )
