"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading: after creating a Team entity, ownership-gated calls MUST
use make_team_owner_headers(team["id"]) — never fall back to the shared
TEST_USERS["team_owner_headers"] constant for ownership-gated paths
(roster mutations, waivers, trade actions, veto votes), per PRD §2.1.
"""
from typing import Optional, List, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_league_payload,
    create_team_payload,
    create_player_payload,
    create_draft_pick_payload,
    create_waiver_claim_payload,
    create_trade_payload,
    create_matchup_payload,
)
from .test_users import TEST_USERS, make_team_owner_headers


# ─── Tier 0: Singletons ────────────────────────────────────────────────────

def set_clock(iso8601: str) -> None:
    """Pin the server's logical clock so accepted_at and created_at are
    deterministic. Commissioner-only per PRD §3.10."""
    api_client.set_clock(iso8601, TEST_USERS["commissioner_headers"])


# ─── Tier 1: Single-entity creators ────────────────────────────────────────

def create_league(**overrides) -> dict:
    """Commissioner creates a league in SETUP state."""
    return get_success_data(
        api_client.create_league(
            create_league_payload(**overrides),
            TEST_USERS["commissioner_headers"],
        )
    )


def create_team(league_id: str, display_name: str = "Test Team",
                division: str = "East", **overrides) -> dict:
    """Commissioner adds a team to a league in SETUP."""
    return get_success_data(
        api_client.create_team(
            league_id,
            create_team_payload(
                display_name=display_name, division=division, **overrides
            ),
            TEST_USERS["commissioner_headers"],
        )
    )


def create_player(full_name: str = "Test Player", position: str = "QB",
                  nfl_team: str = "KC", projected_points: float = 10.0,
                  replacement_value: float = 5.0, **overrides) -> dict:
    """Commissioner seeds a player into the global pool."""
    return get_success_data(
        api_client.create_player(
            create_player_payload(
                full_name=full_name, position=position, nfl_team=nfl_team,
                projected_points=projected_points,
                replacement_value=replacement_value,
                **overrides,
            ),
            TEST_USERS["commissioner_headers"],
        )
    )


def create_draft_pick(league_id: str, team_id: str, player_id: str,
                      round: int, overall_pick: int,
                      cost_cents: int = 0, **overrides) -> dict:
    """Commissioner records a draft pick during DRAFTING."""
    return get_success_data(
        api_client.create_draft_pick(
            create_draft_pick_payload(
                league_id=league_id, team_id=team_id, player_id=player_id,
                round=round, overall_pick=overall_pick, cost_cents=cost_cents,
                **overrides,
            ),
            TEST_USERS["commissioner_headers"],
        )
    )


# ─── Tier 2: League progression to a target state ─────────────────────────

def _get_league_version(league_id: str) -> int:
    league = get_success_data(
        api_client.get_league(league_id, TEST_USERS["commissioner_headers"])
    )
    return league["version"]


def start_draft(league_id: str) -> dict:
    """Transition League SETUP → DRAFTING."""
    v = _get_league_version(league_id)
    return get_success_data(
        api_client.start_draft(league_id, v, TEST_USERS["commissioner_headers"])
    )


def finalize_draft(league_id: str) -> dict:
    """Transition League DRAFTING → IN_SEASON."""
    v = _get_league_version(league_id)
    return get_success_data(
        api_client.finalize_draft(league_id, v, TEST_USERS["commissioner_headers"])
    )


def advance_week(league_id: str) -> dict:
    """Transition League IN_SEASON → IN_SEASON (current_week += 1)."""
    v = _get_league_version(league_id)
    return get_success_data(
        api_client.advance_week(league_id, v, TEST_USERS["commissioner_headers"])
    )


# ─── Tier 3: Full draft+finalize macros ───────────────────────────────────

def _seed_players_for_draft(count: int, prefix: str = "P",
                            positions: Optional[List[str]] = None,
                            projected_points: float = 10.0,
                            replacement_value: float = 5.0) -> List[dict]:
    """Seed `count` players for a draft. Default positions cycle QB/RB/WR/TE
    so a roster_size-by-team-count draft has enough position variety."""
    positions = positions or ["QB", "RB", "WR", "TE", "K", "DEF"]
    nfl_teams = ["KC", "BUF", "MIA", "NYJ", "CIN", "BAL", "PIT", "CLE",
                 "SF", "LAR", "SEA", "DAL", "PHI", "NYG", "WAS", "CHI"]
    players = []
    for i in range(count):
        players.append(
            create_player(
                full_name=f"{prefix}{i + 1}",
                position=positions[i % len(positions)],
                nfl_team=nfl_teams[i % len(nfl_teams)],
                projected_points=projected_points,
                replacement_value=replacement_value,
            )
        )
    return players


def draft_pairs_serpent(
    league_id: str, teams: List[dict], players: List[dict],
) -> List[dict]:
    """Execute a SNAKE-style draft until every team has exactly roster_size
    picks. Returns the list of created DraftPick rows in pick order. Each
    pick has cost_cents=0 (SNAKE constraint).

    The number of players must equal roster_size * len(teams); a longer list
    is silently truncated to that length.
    """
    league = get_success_data(
        api_client.get_league(league_id, TEST_USERS["commissioner_headers"])
    )
    roster_size = league["roster_size"]
    team_count = len(teams)
    expected = roster_size * team_count
    assert len(players) >= expected, (
        f"draft_pairs_serpent needs >= {expected} players but got {len(players)}"
    )
    picks = []
    overall = 1
    for rnd in range(1, roster_size + 1):
        order = teams if rnd % 2 == 1 else list(reversed(teams))
        for team in order:
            player = players[overall - 1]
            picks.append(
                create_draft_pick(
                    league_id, team["id"], player["id"],
                    round=rnd, overall_pick=overall, cost_cents=0,
                )
            )
            overall += 1
    return picks


# ─── Tier 4: End-to-end league-to-IN_SEASON convenience ────────────────────

def setup_in_season_league(
    league_overrides: Optional[dict] = None,
    team_names: Optional[List[str]] = None,
    divisions: Optional[List[str]] = None,
    player_projected: float = 10.0,
    player_replacement: float = 5.0,
) -> dict:
    """Stand up a league through to IN_SEASON, current_week=1.

    Returns dict {league, teams, players, picks}. Teams and players are in
    chronological creation order. Default: 2 teams, both division 'East'.

    Defaults give a league with roster_size=2, starter_slot_count=1,
    ir_slot_count=0; override via league_overrides for richer fixtures.
    """
    league_overrides = dict(league_overrides or {})
    league = create_league(**league_overrides)

    names = team_names or ["Alpha", "Bravo"]
    divs = divisions or ["East"] * len(names)
    assert len(divs) == len(names)
    teams = [create_team(league["id"], n, d) for n, d in zip(names, divs)]

    needed_players = league["roster_size"] * len(teams)
    players = _seed_players_for_draft(
        needed_players,
        projected_points=player_projected,
        replacement_value=player_replacement,
    )

    league = start_draft(league["id"])
    picks = draft_pairs_serpent(league["id"], teams, players)
    league = finalize_draft(league["id"])

    # Re-read teams to capture post-draft (faab_balance, waiver_priority).
    teams = [
        get_success_data(
            api_client.get_team(t["id"], TEST_USERS["commissioner_headers"])
        )
        for t in teams
    ]
    return {
        "league": league,
        "teams": teams,
        "players": players,
        "picks": picks,
    }


# ─── Tier 5: Trade lifecycle shortcuts ─────────────────────────────────────

def propose_trade(
    league_id: str, proposing_team: dict, target_team: dict,
    players_offered: List[str], players_requested: List[str],
    faab_offered_cents: int = 0,
) -> dict:
    """TeamOwner of proposing_team proposes a trade. Returns Trade row.
    Uses make_team_owner_headers(proposing_team.id) for identity threading.
    """
    return get_success_data(
        api_client.create_trade(
            create_trade_payload(
                league_id=league_id,
                proposing_team_id=proposing_team["id"],
                target_team_id=target_team["id"],
                players_offered=players_offered,
                players_requested=players_requested,
                faab_offered_cents=faab_offered_cents,
            ),
            make_team_owner_headers(proposing_team["id"]),
        )
    )


def accept_trade(trade: dict, target_team: dict) -> dict:
    """Target owner accepts a PROPOSED trade. Auto-transitions to
    PENDING_VETO in the same request (PRD §3.8).
    """
    return get_success_data(
        api_client.accept_trade(
            trade["id"], trade["version"],
            make_team_owner_headers(target_team["id"]),
        )
    )


def cast_veto_vote(trade: dict, voter_team: dict, vote: str = "VETO") -> dict:
    """Neutral TeamOwner casts a veto vote against a PENDING_VETO trade."""
    return get_success_data(
        api_client.cast_veto_vote(
            trade["id"], voter_team["id"], vote, trade["version"],
            make_team_owner_headers(voter_team["id"]),
        )
    )


# ─── Tier 6: Matchup lifecycle shortcuts ──────────────────────────────────

def create_regular_matchup(
    league_id: str, week: int, home_team: dict, away_team: dict,
) -> dict:
    """Commissioner creates a REGULAR matchup."""
    return get_success_data(
        api_client.create_matchup(
            league_id,
            create_matchup_payload(
                week=week, matchup_type="REGULAR", round=0,
                home_team_id=home_team["id"], away_team_id=away_team["id"],
            ),
            TEST_USERS["commissioner_headers"],
        )
    )


def start_matchup(matchup: dict) -> dict:
    """Move matchup SCHEDULED → IN_PROGRESS."""
    return get_success_data(
        api_client.start_matchup(
            matchup["id"], matchup["version"],
            TEST_USERS["commissioner_headers"],
        )
    )


def finalize_matchup_with_scores(matchup: dict, home_score: float,
                                 away_score: float) -> dict:
    """Move matchup IN_PROGRESS → COMPLETED with explicit scores."""
    return get_success_data(
        api_client.finalize_matchup(
            matchup["id"], matchup["version"],
            TEST_USERS["commissioner_headers"],
            home_score=home_score, away_score=away_score,
        )
    )


def finalize_matchup_auto(matchup: dict) -> dict:
    """Move matchup IN_PROGRESS → COMPLETED with auto-computed scores via
    injury_replacement_projection (PRD §3.6)."""
    return get_success_data(
        api_client.finalize_matchup(
            matchup["id"], matchup["version"],
            TEST_USERS["commissioner_headers"],
        )
    )


def set_lineup_for_team(team: dict, starter_player_ids: List[str]) -> dict:
    """TeamOwner sets the team's starter lineup (PRD §3.5)."""
    current = get_success_data(
        api_client.get_team(team["id"], TEST_USERS["commissioner_headers"])
    )
    return get_success_data(
        api_client.set_lineup(
            team["id"], starter_player_ids, current["version"],
            make_team_owner_headers(team["id"]),
        )
    )


# ─── Tier 7: Waiver-claim shortcuts ────────────────────────────────────────

def submit_waiver_claim(
    league_id: str, team: dict, player_id: str, bid_cents: int,
    processing_week: int, drop_player_id: Optional[str] = None,
) -> dict:
    """TeamOwner submits a FAAB waiver claim during IN_SEASON."""
    return get_success_data(
        api_client.create_waiver_claim(
            create_waiver_claim_payload(
                league_id=league_id, team_id=team["id"],
                player_id=player_id, bid_cents=bid_cents,
                processing_week=processing_week,
                drop_player_id=drop_player_id,
            ),
            make_team_owner_headers(team["id"]),
        )
    )
