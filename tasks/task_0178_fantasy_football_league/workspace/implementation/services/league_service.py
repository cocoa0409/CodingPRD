"""League CRUD and lifecycle transitions."""
from __future__ import annotations

from typing import Any, Dict, List

from core.errors import (
    err_invalid_state,
    err_keeper_cap_exceeded,
    err_resource_not_found,
    err_validation,
)
from core.store import store
from core.utils import format_iso, parse_iso
from services.timestamps import stamp_create, stamp_update


DEFAULTS = {
    "auction_budget_dollars": 200,
    "keeper_cap": 0,
    "veto_quorum_pct": 50,
    "trade_review_hours": 48,
    "waiver_period_hours": 48,
}


def _validate_int(value, name, lo=None, hi=None, in_set=None):
    if not isinstance(value, int) or isinstance(value, bool):
        raise err_validation(f"{name} must be an integer.")
    if lo is not None and value < lo:
        raise err_validation(f"{name} must be >= {lo}.")
    if hi is not None and value > hi:
        raise err_validation(f"{name} must be <= {hi}.")
    if in_set is not None and value not in in_set:
        raise err_validation(f"{name} must be one of {sorted(in_set)}.")


def _validate_enum(value, name, choices):
    if value not in choices:
        raise err_validation(f"{name} must be one of {sorted(choices)}.")


def _validate_string(value, name, min_len=1, max_len=None):
    if not isinstance(value, str):
        raise err_validation(f"{name} must be a string.")
    if len(value) < min_len:
        raise err_validation(f"{name} length must be >= {min_len}.")
    if max_len is not None and len(value) > max_len:
        raise err_validation(f"{name} length must be <= {max_len}.")


def create_league(body: Dict[str, Any]) -> Dict[str, Any]:
    required = [
        "name",
        "season_year",
        "draft_mode",
        "scoring_mode",
        "team_count",
        "roster_size",
        "starter_count",
        "ir_slots",
        "faab_budget_dollars",
        "keeper_mode",
        "playoff_team_count",
        "regular_season_weeks",
    ]
    for f in required:
        if f not in body:
            raise err_validation(f"Missing required field: {f}.")

    name = body["name"]
    _validate_string(name, "name", 1, 80)

    season_year = body["season_year"]
    _validate_int(season_year, "season_year", lo=2020)

    draft_mode = body["draft_mode"]
    _validate_enum(draft_mode, "draft_mode", {"SNAKE", "AUCTION"})

    scoring_mode = body["scoring_mode"]
    _validate_enum(scoring_mode, "scoring_mode", {"STANDARD", "HALF_PPR", "PPR"})

    team_count = body["team_count"]
    _validate_int(team_count, "team_count", lo=4, hi=16)
    if team_count % 2 != 0:
        raise err_validation("team_count must be an even number.")

    roster_size = body["roster_size"]
    _validate_int(roster_size, "roster_size", lo=12, hi=20)

    starter_count = body["starter_count"]
    _validate_int(starter_count, "starter_count", lo=7, hi=11)

    ir_slots = body["ir_slots"]
    _validate_int(ir_slots, "ir_slots", lo=0, hi=4)

    faab_budget = body["faab_budget_dollars"]
    _validate_int(faab_budget, "faab_budget_dollars", lo=0, hi=1000)

    auction_budget = body.get("auction_budget_dollars", DEFAULTS["auction_budget_dollars"])
    _validate_int(auction_budget, "auction_budget_dollars", lo=0, hi=500)

    keeper_mode = body["keeper_mode"]
    _validate_enum(keeper_mode, "keeper_mode", {"NONE", "REDRAFT", "DYNASTY"})

    keeper_cap = body.get("keeper_cap", DEFAULTS["keeper_cap"])
    _validate_int(keeper_cap, "keeper_cap", lo=0, hi=roster_size - 1)

    veto_quorum_pct = body.get("veto_quorum_pct", DEFAULTS["veto_quorum_pct"])
    _validate_int(veto_quorum_pct, "veto_quorum_pct", lo=25, hi=100)

    trade_review_hours = body.get("trade_review_hours", DEFAULTS["trade_review_hours"])
    _validate_int(trade_review_hours, "trade_review_hours", lo=0, hi=168)

    waiver_period_hours = body.get("waiver_period_hours", DEFAULTS["waiver_period_hours"])
    _validate_int(waiver_period_hours, "waiver_period_hours", lo=0, hi=168)

    playoff_team_count = body["playoff_team_count"]
    _validate_int(playoff_team_count, "playoff_team_count", in_set={2, 4, 8})

    regular_season_weeks = body["regular_season_weeks"]
    _validate_int(regular_season_weeks, "regular_season_weeks", lo=10, hi=14)

    league = {
        "name": name,
        "season_year": season_year,
        "draft_mode": draft_mode,
        "scoring_mode": scoring_mode,
        "team_count": team_count,
        "roster_size": roster_size,
        "starter_count": starter_count,
        "ir_slots": ir_slots,
        "faab_budget_dollars": faab_budget,
        "auction_budget_dollars": auction_budget,
        "keeper_mode": keeper_mode,
        "keeper_cap": keeper_cap,
        "veto_quorum_pct": veto_quorum_pct,
        "trade_review_hours": trade_review_hours,
        "waiver_period_hours": waiver_period_hours,
        "playoff_team_count": playoff_team_count,
        "regular_season_weeks": regular_season_weeks,
        "status": "DRAFT_PENDING",
        "current_week": 0,
    }
    stamp_create(league)
    league["now_ts"] = league["created_at"]
    store.leagues[league["id"]] = league
    store.drop_history[league["id"]] = []
    return league


def get_league(league_id: str) -> Dict[str, Any]:
    league = store.leagues.get(league_id)
    if not league:
        raise err_resource_not_found(f"League {league_id} not found.")
    return league


def list_leagues() -> List[Dict[str, Any]]:
    items = list(store.leagues.values())
    items.sort(key=lambda x: x["created_at"])
    return items


def start_draft(league_id: str) -> Dict[str, Any]:
    league = get_league(league_id)
    if league["status"] != "DRAFT_PENDING":
        raise err_invalid_state(
            f"League cannot start draft from status {league['status']}."
        )

    teams = store.teams_in_league(league_id)
    if len(teams) != league["team_count"]:
        raise err_invalid_state(
            f"Team count {len(teams)} != league.team_count {league['team_count']}."
        )

    # Validate keeper_cap not exceeded per team
    for team in teams:
        declared = [
            k
            for k in store.keepers_for_team(team["id"])
            if k["status"] == "DECLARED"
        ]
        if len(declared) > league["keeper_cap"]:
            raise err_keeper_cap_exceeded(
                f"Team {team['id']} has {len(declared)} keepers > cap {league['keeper_cap']}."
            )

    # Assign draft_position 1..team_count by team.created_at ascending
    teams_sorted = sorted(teams, key=lambda t: t["created_at"])
    for idx, team in enumerate(teams_sorted, start=1):
        team["draft_position"] = idx
        stamp_update(team)

    # Set auction balances
    for team in teams_sorted:
        if league["draft_mode"] == "AUCTION":
            team["auction_balance_dollars"] = league["auction_budget_dollars"]
        else:
            team["auction_balance_dollars"] = 0
        stamp_update(team)

    # Process locked keepers
    from services import keeper_service
    keeper_service.lock_declared_keepers(league)

    league["status"] = "DRAFTING"
    stamp_update(league)
    return league


def finish_draft(league_id: str) -> Dict[str, Any]:
    league = get_league(league_id)
    if league["status"] != "DRAFTING":
        raise err_invalid_state(
            f"League cannot finish draft from status {league['status']}."
        )

    expected_picks = league["team_count"] * (league["roster_size"] - league["ir_slots"])
    league_picks = store.draft_picks_in_league(league_id)
    if len(league_picks) != expected_picks:
        raise err_invalid_state(
            f"Draft pick count {len(league_picks)} != expected {expected_picks}."
        )
    # Uniqueness of player_id
    seen = set()
    for p in league_picks:
        if p["player_id"] in seen:
            raise err_invalid_state(
                f"Duplicate player_id {p['player_id']} in draft picks."
            )
        seen.add(p["player_id"])

    league["current_week"] = 1

    # Materialize roster slots from picks
    from services import roster_service
    for pick in league_picks:
        roster_service.insert_bench_slot(pick["team_id"], pick["player_id"])

    # Auto-initialize each team's starting lineup so the
    # team has exactly league.starter_count STARTER slots.
    # PRD §3.4(c) requires starters to equal starter_count
    # after any roster mutation; the system bootstraps that
    # invariant immediately after finish-draft.
    _auto_initialize_starters(league)

    # Convert LOCKED keepers
    for k in list(store.keeper_designations.values()):
        if k["league_id"] == league_id and k["status"] == "LOCKED":
            k["status"] = "CONVERTED"
            stamp_update(k)

    # Generate matchups for regular season
    from services import matchup_service
    matchup_service.generate_regular_season(league)

    league["status"] = "REGULAR_SEASON"
    stamp_update(league)
    return league


def _starter_label_plan(starter_count: int):
    """Pick a deterministic plan of starter labels for a given starter_count.
    Total labels must equal starter_count. Labels must be unique.

    For starter_count==10, PRD §3.4(d) names the exact composition:
      1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX, 1 K, 1 DST = 10.
    For other starter_counts in PRD's range 7..11, choose a natural
    composition that picks the same position labels (QB1, RB1, RB2,
    WR1, WR2, WR3, TE1, FLEX, K1, DST1) in order until starter_count
    is reached. starter_count=7 → 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX.
    """
    base = ["QB1", "RB1", "RB2", "WR1", "WR2", "WR3", "TE1", "FLEX", "K1", "DST1", "WR4"]
    return base[:starter_count]


_POSITION_ROOT = {"QB", "RB", "WR", "TE", "K", "DST"}
_FLEX_ROOTS = {"RB", "WR", "TE"}


def _label_root(label: str):
    if label == "FLEX":
        return "FLEX"
    i = len(label)
    while i > 0 and label[i - 1].isdigit():
        i -= 1
    return label[:i]


def _player_fits_label(player_position: str, label: str) -> bool:
    if label == "FLEX":
        return player_position in {"RB", "WR", "TE", "FLEX_RWT"}
    root = _label_root(label)
    if root in _POSITION_ROOT:
        if player_position == root:
            return True
        if player_position == "FLEX_RWT" and root in _FLEX_ROOTS:
            return True
    return False


def _auto_initialize_starters(league: Dict[str, Any]) -> None:
    """For each team, promote BENCH slots to STARTER such that the team
    ends up with exactly league.starter_count starters, with unique
    position labels from the natural plan."""
    from services.timestamps import stamp_update

    labels = _starter_label_plan(league["starter_count"])
    teams = store.teams_in_league(league["id"])
    for team in teams:
        team_slots = store.roster_slots_for_team(team["id"])
        # Map slot.id → player position
        slot_to_pos = {}
        for s in team_slots:
            p = store.players.get(s["player_id"])
            slot_to_pos[s["id"]] = p.get("position") if p else None

        used_slots = set()
        for label in labels:
            chosen = None
            # First pass: strict position match
            for s in team_slots:
                if s["id"] in used_slots:
                    continue
                if s["slot_type"] != "BENCH":
                    continue
                pos = slot_to_pos.get(s["id"])
                if pos and _player_fits_label(pos, label):
                    chosen = s
                    break
            if chosen is None:
                # If no fit, leave label unfilled (next mutation will
                # surface the shape error).
                continue
            chosen["slot_type"] = "STARTER"
            chosen["position_label"] = label
            used_slots.add(chosen["id"])
            stamp_update(chosen)


def archive_league(league_id: str) -> Dict[str, Any]:
    league = get_league(league_id)
    if league["status"] != "COMPLETED":
        raise err_invalid_state(
            f"League cannot archive from status {league['status']}."
        )
    # Cancel pending waivers
    for w in list(store.waiver_claims.values()):
        if w["league_id"] == league_id and w["status"] == "PENDING":
            w["status"] = "CANCELED"
            stamp_update(w)
    # Reject open trades
    for t in list(store.trade_proposals.values()):
        if t["league_id"] == league_id and t["status"] in {
            "OFFERED",
            "ACCEPTED_PENDING_REVIEW",
        }:
            t["status"] = "REJECTED"
            stamp_update(t)
    league["status"] = "ARCHIVED"
    stamp_update(league)
    return league


def advance_clock(league_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    league = get_league(league_id)
    target_ts = body.get("target_ts")
    if not target_ts:
        raise err_validation("target_ts is required.")
    try:
        target_dt = parse_iso(target_ts)
    except ValueError:
        raise err_validation(f"Invalid target_ts: {target_ts}.")
    current_dt = parse_iso(league["now_ts"])
    if target_dt < current_dt:
        raise err_validation("target_ts cannot move clock backward.")

    league["now_ts"] = format_iso(target_dt)
    stamp_update(league)

    # Order of cascades:
    # 1) Weekly locks (any SCHEDULED matchup whose lock instant is reached)
    # 2) Waiver settlement
    # 3) Trade reviews (execute or expire)
    # 4) Regular-season -> Playoffs evaluation
    from services import matchup_service, waiver_service, trade_service

    matchup_service.cascade_locks(league)
    waiver_service.process_due(league)
    trade_service.process_expired_trades(league)
    matchup_service.evaluate_lifecycle_transition(league)

    return league
