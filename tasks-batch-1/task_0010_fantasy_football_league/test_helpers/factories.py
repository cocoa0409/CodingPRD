"""Payload factories — one per entity, input fields only."""
from typing import Optional, List


def create_league_payload(
    name: str = "Test League",
    draft_type: str = "SNAKE",
    roster_size: int = 2,
    starter_slot_count: int = 1,
    ir_slot_count: int = 0,
    faab_budget_cents: int = 5000,
    veto_threshold: int = 1,
    keeper_limit: int = 0,
    playoff_team_count: int = 2,
    tiebreak_rule: str = "STANDARD",
    **overrides,
) -> dict:
    """POST /leagues."""
    defaults = {
        "name": name,
        "draft_type": draft_type,
        "roster_size": roster_size,
        "starter_slot_count": starter_slot_count,
        "ir_slot_count": ir_slot_count,
        "faab_budget_cents": faab_budget_cents,
        "veto_threshold": veto_threshold,
        "keeper_limit": keeper_limit,
        "playoff_team_count": playoff_team_count,
        "tiebreak_rule": tiebreak_rule,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(
    display_name: str = "Test Team",
    division: str = "East",
    **overrides,
) -> dict:
    """POST /leagues/{id}/teams."""
    defaults = {
        "display_name": display_name,
        "division": division,
    }
    defaults.update(overrides)
    return defaults


def create_player_payload(
    full_name: str = "Test Player",
    position: str = "QB",
    nfl_team: str = "KC",
    projected_points: float = 10.0,
    replacement_value: float = 5.0,
    **overrides,
) -> dict:
    """POST /players."""
    defaults = {
        "full_name": full_name,
        "position": position,
        "nfl_team": nfl_team,
        "projected_points": projected_points,
        "replacement_value": replacement_value,
    }
    defaults.update(overrides)
    return defaults


def create_draft_pick_payload(
    league_id: str,
    team_id: str,
    player_id: str,
    round: int = 1,
    overall_pick: int = 1,
    cost_cents: int = 0,
    keeper_round: Optional[int] = None,
    is_keeper: Optional[bool] = None,
    **overrides,
) -> dict:
    """POST /draft-picks."""
    defaults = {
        "league_id": league_id,
        "team_id": team_id,
        "player_id": player_id,
        "round": round,
        "overall_pick": overall_pick,
        "cost_cents": cost_cents,
    }
    if keeper_round is not None:
        defaults["keeper_round"] = keeper_round
    if is_keeper is not None:
        defaults["is_keeper"] = is_keeper
    defaults.update(overrides)
    return defaults


def create_waiver_claim_payload(
    league_id: str,
    team_id: str,
    player_id: str,
    bid_cents: int,
    processing_week: int,
    drop_player_id: Optional[str] = None,
    **overrides,
) -> dict:
    """POST /waiver-claims."""
    defaults = {
        "league_id": league_id,
        "team_id": team_id,
        "player_id": player_id,
        "bid_cents": bid_cents,
        "processing_week": processing_week,
    }
    if drop_player_id is not None:
        defaults["drop_player_id"] = drop_player_id
    defaults.update(overrides)
    return defaults


def create_trade_payload(
    league_id: str,
    proposing_team_id: str,
    target_team_id: str,
    players_offered: List[str],
    players_requested: List[str],
    faab_offered_cents: int = 0,
    **overrides,
) -> dict:
    """POST /trades."""
    defaults = {
        "league_id": league_id,
        "proposing_team_id": proposing_team_id,
        "target_team_id": target_team_id,
        "players_offered": list(players_offered),
        "players_requested": list(players_requested),
        "faab_offered_cents": faab_offered_cents,
    }
    defaults.update(overrides)
    return defaults


def create_matchup_payload(
    week: int,
    home_team_id: str,
    away_team_id: str,
    matchup_type: str = "REGULAR",
    round: int = 0,
    **overrides,
) -> dict:
    """POST /leagues/{id}/matchups."""
    defaults = {
        "week": week,
        "matchup_type": matchup_type,
        "round": round,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
    }
    defaults.update(overrides)
    return defaults
