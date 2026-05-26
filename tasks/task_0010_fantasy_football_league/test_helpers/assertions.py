"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_LEAGUE_STATUSES = {"SETUP", "DRAFTING", "IN_SEASON", "PLAYOFFS", "COMPLETE"}
_DRAFT_TYPES = {"SNAKE", "AUCTION"}
_TIEBREAK_RULES = {"STANDARD", "DIVISION_FIRST"}
_PLAYER_STATUSES = {"ACTIVE", "INJURED", "IR_PLACED", "RELEASED"}
_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
_SLOT_TYPES = {"STARTER", "BENCH", "IR"}
_WAIVER_STATES = {"SUBMITTED", "WON", "LOST_BID", "INVALID", "CANCELLED"}
_TRADE_STATES = {"PROPOSED", "ACCEPTED", "PENDING_VETO", "VETOED",
                 "EXECUTED", "REJECTED", "WITHDRAWN"}
_MATCHUP_TYPES = {"REGULAR", "PLAYOFF"}
_MATCHUP_STATES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED"}
_VETO_VOTES = {"VETO", "ALLOW"}


def _assert_common_fields(data: dict, label: str) -> None:
    """Validate id + created_at + updated_at + version (common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_league(data: dict) -> None:
    _assert_common_fields(data, "League")
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 80
    assert data.get("draft_type") in _DRAFT_TYPES
    assert isinstance(data.get("roster_size"), int)
    assert 2 <= data["roster_size"] <= 20
    assert isinstance(data.get("starter_slot_count"), int)
    assert 1 <= data["starter_slot_count"] <= 11
    assert data["starter_slot_count"] <= data["roster_size"]
    assert isinstance(data.get("ir_slot_count"), int)
    assert 0 <= data["ir_slot_count"] <= 3
    assert isinstance(data.get("faab_budget_cents"), int)
    assert 0 <= data["faab_budget_cents"] <= 1_000_000
    assert isinstance(data.get("veto_threshold"), int) and data["veto_threshold"] >= 1
    assert isinstance(data.get("keeper_limit"), int)
    assert 0 <= data["keeper_limit"] <= 6
    assert data.get("playoff_team_count") in {2, 4, 8}
    assert data.get("tiebreak_rule") in _TIEBREAK_RULES
    assert data.get("status") in _LEAGUE_STATUSES
    assert isinstance(data.get("current_week"), int)
    assert 0 <= data["current_week"] <= 17
    assert isinstance(data.get("total_faab_pool_cents"), int)
    assert data["total_faab_pool_cents"] >= 0


def assert_team(data: dict) -> None:
    _assert_common_fields(data, "Team")
    assert is_valid_uuid(data.get("league_id", ""))
    assert isinstance(data.get("display_name"), str)
    assert 1 <= len(data["display_name"]) <= 40
    assert isinstance(data.get("division"), str)
    assert 1 <= len(data["division"]) <= 20
    assert isinstance(data.get("faab_balance_cents"), int)
    assert data["faab_balance_cents"] >= 0
    assert isinstance(data.get("wins"), int) and data["wins"] >= 0
    assert isinstance(data.get("losses"), int) and data["losses"] >= 0
    assert isinstance(data.get("total_points_for"), (int, float))
    assert isinstance(data.get("total_points_against"), (int, float))
    assert isinstance(data.get("intra_division_wins"), int)
    assert data["intra_division_wins"] >= 0
    assert isinstance(data.get("playoff_seed"), int) and data["playoff_seed"] >= 0
    keepers = data.get("keeper_player_ids", [])
    assert isinstance(keepers, list)


def assert_player(data: dict) -> None:
    _assert_common_fields(data, "Player")
    assert isinstance(data.get("full_name"), str)
    assert 1 <= len(data["full_name"]) <= 80
    assert data.get("position") in _POSITIONS
    nfl_team = data.get("nfl_team", "")
    assert nfl_team == "FA" or (2 <= len(nfl_team) <= 3 and nfl_team.isupper())
    assert data.get("status") in _PLAYER_STATUSES
    assert isinstance(data.get("projected_points"), (int, float))
    assert 0.0 <= float(data["projected_points"]) <= 50.0
    assert isinstance(data.get("replacement_value"), (int, float))
    assert 0.0 <= float(data["replacement_value"]) <= 30.0
    cti = data.get("current_team_id")
    assert cti is None or is_valid_uuid(cti)


def assert_draft_pick(data: dict) -> None:
    _assert_common_fields(data, "DraftPick")
    assert is_valid_uuid(data.get("league_id", ""))
    assert is_valid_uuid(data.get("team_id", ""))
    assert is_valid_uuid(data.get("player_id", ""))
    assert isinstance(data.get("round"), int) and 1 <= data["round"] <= 20
    assert isinstance(data.get("overall_pick"), int) and data["overall_pick"] >= 1
    assert isinstance(data.get("cost_cents"), int) and data["cost_cents"] >= 0


def assert_roster_slot(data: dict) -> None:
    _assert_common_fields(data, "RosterSlot")
    assert is_valid_uuid(data.get("team_id", ""))
    assert is_valid_uuid(data.get("player_id", ""))
    assert data.get("slot_type") in _SLOT_TYPES


def assert_waiver_claim(data: dict) -> None:
    _assert_common_fields(data, "WaiverClaim")
    assert is_valid_uuid(data.get("league_id", ""))
    assert is_valid_uuid(data.get("team_id", ""))
    assert is_valid_uuid(data.get("player_id", ""))
    assert isinstance(data.get("bid_cents"), int) and data["bid_cents"] >= 0
    assert data.get("state") in _WAIVER_STATES
    assert isinstance(data.get("processing_week"), int)


def assert_trade(data: dict) -> None:
    _assert_common_fields(data, "Trade")
    assert is_valid_uuid(data.get("league_id", ""))
    assert is_valid_uuid(data.get("proposing_team_id", ""))
    assert is_valid_uuid(data.get("target_team_id", ""))
    assert data["proposing_team_id"] != data["target_team_id"]
    assert isinstance(data.get("players_offered"), list)
    assert 1 <= len(data["players_offered"]) <= 5
    assert isinstance(data.get("players_requested"), list)
    assert 1 <= len(data["players_requested"]) <= 5
    assert isinstance(data.get("faab_offered_cents"), int)
    assert data["faab_offered_cents"] >= 0
    assert data.get("state") in _TRADE_STATES
    assert isinstance(data.get("veto_votes_count"), int)
    assert data["veto_votes_count"] >= 0


def assert_veto_vote(data: dict) -> None:
    """VetoVote — PRD §2.4: 'an immutable audit record — it carries only id
    and created_at, with no updated_at and no version.'
    """
    assert is_valid_uuid(data.get("id", "")), "VetoVote.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "VetoVote.created_at must be ISO 8601"
    )
    assert is_valid_uuid(data.get("trade_id", ""))
    assert is_valid_uuid(data.get("voter_team_id", ""))
    assert data.get("vote") in _VETO_VOTES


def assert_playoff_matchup(data: dict) -> None:
    _assert_common_fields(data, "PlayoffMatchup")
    assert is_valid_uuid(data.get("league_id", ""))
    assert isinstance(data.get("week"), int) and 1 <= data["week"] <= 17
    assert data.get("matchup_type") in _MATCHUP_TYPES
    assert isinstance(data.get("round"), int) and 0 <= data["round"] <= 3
    assert is_valid_uuid(data.get("home_team_id", ""))
    assert is_valid_uuid(data.get("away_team_id", ""))
    assert data["home_team_id"] != data["away_team_id"]
    assert isinstance(data.get("home_score"), (int, float))
    assert isinstance(data.get("away_score"), (int, float))
    assert data.get("state") in _MATCHUP_STATES
    winner = data.get("winner_team_id")
    assert winner is None or is_valid_uuid(winner)


def assert_total_faab_pool_invariant(league: dict, teams: list) -> None:
    """PRD §1: 'FAAB is a conserved pool ... the sum of every team's FAAB
    balance never drifts from the league's starting total even as it moves
    between balance sheets.'

    league.total_faab_pool_cents must equal the sum of every team's
    faab_balance_cents in the league (post-draft).
    """
    pool = league.get("total_faab_pool_cents")
    summed = sum(t.get("faab_balance_cents", 0) for t in teams)
    assert pool == summed, (
        f"FAAB invariant: total_faab_pool_cents={pool} but "
        f"sum(team.faab_balance_cents)={summed}"
    )
