"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. PRD §2.4 distinguishes:
- Primary entities (League, Team, Player, RosterSlot, WaiverClaim,
  TradeProposal, MatchupWeek, KeeperDesignation) carry id, created_at,
  updated_at, version.
- Immutable-with-respect-to-update entities (DraftPick, TradeVote)
  carry only id and created_at — assertions on those entities MUST NOT
  demand updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Generic utilities
# ---------------------------------------------------------------------------
def _assert_uuid(value: Any, label: str) -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_valid_uuid(value), f"{label} must be a valid UUID (PRD §2.4), got {value!r}"


def _assert_timestamp(value: Any, label: str) -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_iso8601_timestamp(value), \
        f"{label} must be ISO 8601 UTC w/ three fractional digits (PRD §2.4), got {value!r}"


def _assert_common_versioned(entity: Dict[str, Any], name: str) -> None:
    """PRD §2.4: primary entities carry id/created_at/updated_at/version."""
    _assert_uuid(entity.get("id"), f"{name}.id")
    _assert_timestamp(entity.get("created_at"), f"{name}.created_at")
    _assert_timestamp(entity.get("updated_at"), f"{name}.updated_at")
    assert isinstance(entity.get("version"), int), \
        f"{name}.version must be int, got {type(entity.get('version')).__name__}"
    assert entity["version"] >= 1, f"{name}.version must be >= 1"


def _assert_immutable_audit(entity: Dict[str, Any], name: str) -> None:
    """PRD §2.4: DraftPick and TradeVote carry only id + created_at."""
    _assert_uuid(entity.get("id"), f"{name}.id")
    _assert_timestamp(entity.get("created_at"), f"{name}.created_at")


def find_by_id(items: Iterable[Dict[str, Any]], item_id: str) -> Optional[Dict[str, Any]]:
    for it in items:
        if it.get("id") == item_id:
            return it
    return None


# ---------------------------------------------------------------------------
# League (PRD §3.1, §3.8)
# ---------------------------------------------------------------------------
LEAGUE_STATUSES = {
    "DRAFT_PENDING", "DRAFTING", "REGULAR_SEASON", "PLAYOFFS",
    "COMPLETED", "ARCHIVED",
}
DRAFT_MODES = {"SNAKE", "AUCTION"}
SCORING_MODES = {"STANDARD", "HALF_PPR", "PPR"}
KEEPER_MODES = {"NONE", "REDRAFT", "DYNASTY"}


def assert_league(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "League")
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data.get("season_year"), int) and data["season_year"] >= 2020
    assert data.get("draft_mode") in DRAFT_MODES
    assert data.get("scoring_mode") in SCORING_MODES
    tc = data.get("team_count")
    assert isinstance(tc, int) and 4 <= tc <= 16 and tc % 2 == 0
    rs = data.get("roster_size")
    assert isinstance(rs, int) and 12 <= rs <= 20
    sc = data.get("starter_count")
    assert isinstance(sc, int) and 7 <= sc <= 11
    ir = data.get("ir_slots")
    assert isinstance(ir, int) and 0 <= ir <= 4
    fb = data.get("faab_budget_dollars")
    assert isinstance(fb, int) and 0 <= fb <= 1000
    assert data.get("keeper_mode") in KEEPER_MODES
    pt = data.get("playoff_team_count")
    assert pt in (2, 4, 8)
    rsw = data.get("regular_season_weeks")
    assert isinstance(rsw, int) and 10 <= rsw <= 14
    assert data.get("status") in LEAGUE_STATUSES
    cw = data.get("current_week")
    assert isinstance(cw, int)
    _assert_timestamp(data.get("now_ts"), "League.now_ts")


# ---------------------------------------------------------------------------
# Team (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_team(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Team")
    _assert_uuid(data.get("league_id"), "Team.league_id")
    nm = data.get("name")
    assert isinstance(nm, str) and 1 <= len(nm) <= 60
    assert isinstance(data.get("manager_user_id"), str) and data["manager_user_id"]
    # draft_position is null while DRAFT_PENDING, integer afterward
    dp = data.get("draft_position")
    assert dp is None or (isinstance(dp, int) and dp >= 1)
    fab = data.get("faab_balance_dollars")
    assert isinstance(fab, int) and fab >= 0
    ab = data.get("auction_balance_dollars")
    assert isinstance(ab, int) and ab >= 0
    assert isinstance(data.get("wins"), int) and data["wins"] >= 0
    assert isinstance(data.get("losses"), int) and data["losses"] >= 0
    pf = data.get("points_for")
    assert isinstance(pf, (int, float)) and float(pf) >= 0
    ss = data.get("standing_seed")
    assert ss is None or (isinstance(ss, int) and ss >= 1)


# ---------------------------------------------------------------------------
# Player (PRD §3.1)
# ---------------------------------------------------------------------------
PLAYER_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "FLEX_RWT"}
PLAYER_STATUS_TAGS = {"ACTIVE", "QUESTIONABLE", "OUT", "IR_ELIGIBLE"}


def assert_player(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Player")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("nfl_team"), str) and data["nfl_team"]
    assert data.get("position") in PLAYER_POSITIONS
    assert data.get("status_tag") in PLAYER_STATUS_TAGS
    wpp = data.get("weekly_proj_points")
    assert isinstance(wpp, (int, float))


# ---------------------------------------------------------------------------
# DraftPick (PRD §2.4 — immutable-with-respect-to-update)
# ---------------------------------------------------------------------------
def assert_draft_pick(data: Dict[str, Any]) -> None:
    """PRD §2.4: DraftPick carries id and created_at only — no
    updated_at / version."""
    _assert_immutable_audit(data, "DraftPick")
    _assert_uuid(data.get("league_id"), "DraftPick.league_id")
    _assert_uuid(data.get("team_id"), "DraftPick.team_id")
    _assert_uuid(data.get("player_id"), "DraftPick.player_id")
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 0
    opi = data.get("overall_pick_index")
    assert isinstance(opi, int) and opi >= 1
    pd = data.get("price_dollars")
    assert isinstance(pd, int) and pd >= 0
    assert isinstance(data.get("is_keeper"), bool)
    # PRD §2.4: DraftPick must NOT carry updated_at / version.
    assert "updated_at" not in data or data["updated_at"] is None, \
        "DraftPick must NOT carry updated_at (PRD §2.4)"
    assert "version" not in data or data["version"] is None, \
        "DraftPick must NOT carry version (PRD §2.4)"


# ---------------------------------------------------------------------------
# RosterSlot (PRD §3.4)
# ---------------------------------------------------------------------------
SLOT_TYPES = {"STARTER", "BENCH", "IR"}


def assert_roster_slot(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "RosterSlot")
    _assert_uuid(data.get("team_id"), "RosterSlot.team_id")
    _assert_uuid(data.get("player_id"), "RosterSlot.player_id")
    assert data.get("slot_type") in SLOT_TYPES
    pl = data.get("position_label")
    if data["slot_type"] == "STARTER":
        assert isinstance(pl, str) and pl, \
            "Starter RosterSlot.position_label required (PRD §3.4)"
    else:
        # BENCH/IR position_label is null per PRD §3.4.
        assert pl is None, \
            f"BENCH/IR RosterSlot.position_label must be null (PRD §3.4), got {pl!r}"


# ---------------------------------------------------------------------------
# WaiverClaim (PRD §3.6)
# ---------------------------------------------------------------------------
WAIVER_STATUSES = {"PENDING", "AWARDED", "LOST", "CANCELED"}


def assert_waiver_claim(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "WaiverClaim")
    _assert_uuid(data.get("league_id"), "WaiverClaim.league_id")
    _assert_uuid(data.get("team_id"), "WaiverClaim.team_id")
    _assert_uuid(data.get("add_player_id"), "WaiverClaim.add_player_id")
    dp = data.get("drop_player_id")
    assert dp is None or is_valid_uuid(dp), \
        "WaiverClaim.drop_player_id must be null or UUID"
    bd = data.get("bid_dollars")
    assert isinstance(bd, int) and bd >= 0
    ps = data.get("priority_seed")
    assert isinstance(ps, int) and ps >= 1
    assert data.get("status") in WAIVER_STATUSES
    _assert_timestamp(data.get("settle_ts"), "WaiverClaim.settle_ts")


# ---------------------------------------------------------------------------
# TradeProposal (PRD §3.7)
# ---------------------------------------------------------------------------
TRADE_STATUSES = {
    "OFFERED", "ACCEPTED_PENDING_REVIEW", "VETOED", "EXECUTED",
    "REJECTED", "EXPIRED", "CANCELED",
}


def assert_trade_proposal(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "TradeProposal")
    _assert_uuid(data.get("league_id"), "TradeProposal.league_id")
    _assert_uuid(data.get("proposing_team_id"), "TradeProposal.proposing_team_id")
    _assert_uuid(data.get("counterparty_team_id"), "TradeProposal.counterparty_team_id")
    sp = data.get("send_player_ids")
    rp = data.get("receive_player_ids")
    assert isinstance(sp, list) and sp, "TradeProposal.send_player_ids non-empty list"
    assert isinstance(rp, list) and rp, "TradeProposal.receive_player_ids non-empty list"
    for pid in sp + rp:
        assert is_valid_uuid(pid), f"TradeProposal player ids must be UUID, got {pid!r}"
    sfd = data.get("send_faab_dollars")
    rfd = data.get("receive_faab_dollars")
    assert isinstance(sfd, int) and sfd >= 0
    assert isinstance(rfd, int) and rfd >= 0
    # PRD §3.7: no two-way money.
    assert not (sfd > 0 and rfd > 0), \
        "PRD §3.7: at most one direction of FAAB may be non-zero"
    assert data.get("status") in TRADE_STATUSES
    vc = data.get("veto_count")
    assert isinstance(vc, int) and vc >= 0


# ---------------------------------------------------------------------------
# TradeVote (PRD §2.4 — immutable)
# ---------------------------------------------------------------------------
TRADE_VOTE_VALUES = {"VETO", "APPROVE"}


def assert_trade_vote(data: Dict[str, Any]) -> None:
    """PRD §2.4: TradeVote carries id, trade_proposal_id, voting_team_id,
    vote, and cast_at_ts — no updated_at / version."""
    _assert_immutable_audit(data, "TradeVote")
    _assert_uuid(data.get("trade_proposal_id"), "TradeVote.trade_proposal_id")
    _assert_uuid(data.get("voting_team_id"), "TradeVote.voting_team_id")
    assert data.get("vote") in TRADE_VOTE_VALUES
    _assert_timestamp(data.get("cast_at_ts"), "TradeVote.cast_at_ts")
    assert "updated_at" not in data or data["updated_at"] is None, \
        "TradeVote must NOT carry updated_at (PRD §2.4)"
    assert "version" not in data or data["version"] is None, \
        "TradeVote must NOT carry version (PRD §2.4)"


# ---------------------------------------------------------------------------
# MatchupWeek (PRD §3.5)
# ---------------------------------------------------------------------------
MATCHUP_STATUSES = {"SCHEDULED", "LOCKED", "SCORED"}


def assert_matchup_week(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "MatchupWeek")
    _assert_uuid(data.get("league_id"), "MatchupWeek.league_id")
    assert isinstance(data.get("week_number"), int) and data["week_number"] >= 1
    _assert_uuid(data.get("home_team_id"), "MatchupWeek.home_team_id")
    _assert_uuid(data.get("away_team_id"), "MatchupWeek.away_team_id")
    for fld in ("home_points", "away_points"):
        val = data.get(fld)
        assert isinstance(val, (int, float)), f"MatchupWeek.{fld} must be number"
    assert data.get("status") in MATCHUP_STATUSES
    assert isinstance(data.get("is_playoff"), bool)
    br = data.get("bracket_round")
    if data.get("is_playoff"):
        assert isinstance(br, int) and br >= 1, \
            "MatchupWeek.bracket_round must be set for playoff matchups (PRD §3.5)"
    else:
        assert br is None, \
            "MatchupWeek.bracket_round must be null when is_playoff=false (PRD §3.5)"


# ---------------------------------------------------------------------------
# KeeperDesignation (PRD §3.2)
# ---------------------------------------------------------------------------
KEEPER_STATUSES = {"DECLARED", "LOCKED", "CONVERTED", "REVOKED"}


def assert_keeper_designation(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "KeeperDesignation")
    _assert_uuid(data.get("league_id"), "KeeperDesignation.league_id")
    _assert_uuid(data.get("team_id"), "KeeperDesignation.team_id")
    _assert_uuid(data.get("player_id"), "KeeperDesignation.player_id")
    assert isinstance(data.get("season_year"), int)
    assert data.get("status") in KEEPER_STATUSES


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_money_precision_two_decimals(value: float, label: str) -> None:
    """PRD §2.10 / §3.5: points are stored to exactly two decimals."""
    rounded = round(float(value), 2)
    assert abs(float(value) - rounded) < 1e-9, \
        f"{label}={value!r} must be representable at two decimals (PRD §2.10 / §3.5)"


def assert_faab_total_conserved(teams_before: List[Dict[str, Any]],
                                 teams_after: List[Dict[str, Any]]) -> None:
    """PRD §2.11: FAAB is per-team and decremented only on award; FAAB
    transfers in trades move dollars between teams. The league-wide sum
    is conserved across a trade execution."""
    sum_before = sum(t["faab_balance_dollars"] for t in teams_before)
    sum_after = sum(t["faab_balance_dollars"] for t in teams_after)
    assert sum_before == sum_after, \
        f"Sum of Team.faab_balance_dollars must be conserved across a trade ({sum_before} != {sum_after})"


def assert_league_roster_count_conserved(slots_before: int, slots_after: int) -> None:
    """PRD §3.7: trade execution swaps RosterSlot ownership but does not
    add or remove rows in the league."""
    assert slots_before == slots_after, \
        f"Total RosterSlot count must be conserved across trade execution ({slots_before} != {slots_after})"


__all__ = [
    "assert_league",
    "assert_team",
    "assert_player",
    "assert_draft_pick",
    "assert_roster_slot",
    "assert_waiver_claim",
    "assert_trade_proposal",
    "assert_trade_vote",
    "assert_matchup_week",
    "assert_keeper_designation",
    "assert_money_precision_two_decimals",
    "assert_faab_total_conserved",
    "assert_league_roster_count_conserved",
    "find_by_id",
    "LEAGUE_STATUSES",
    "DRAFT_MODES",
    "SCORING_MODES",
    "KEEPER_MODES",
    "PLAYER_POSITIONS",
    "PLAYER_STATUS_TAGS",
    "SLOT_TYPES",
    "WAIVER_STATUSES",
    "TRADE_STATUSES",
    "TRADE_VOTE_VALUES",
    "MATCHUP_STATUSES",
    "KEEPER_STATUSES",
]
