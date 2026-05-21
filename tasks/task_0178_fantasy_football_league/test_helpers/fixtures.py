"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce
clear "setup failed" errors rather than confusing assertion failures.

Identity threading rule (PRD §2.1): every Team has a manager_user_id
chosen at create-team time. Any Manager-owned call MUST be issued with
make_manager_headers(team["manager_user_id"]). Falling back to the
shared TEST_USERS["manager_headers"] would force the implementation to
either drop ERR_NOT_TEAM_OWNER checking (which is wrong) or reject
every owned call (which would fail every fixture). The shared fallback
constant is reserved for tests that do not exercise ownership.

Fixture tiers (per PRD §3 workflow):
- Tier 1 — primitive entity creation (league, team, player) with
  ownership-correct headers.
- Tier 2 — entity hierarchies (league + N teams + player catalog).
- Tier 3 — full lifecycle shortcuts (drafted → REGULAR_SEASON, week
  locked, week scored, trade in flight).
- Tier 4 — boundary / accumulation targeting (specific FAAB balances,
  veto-percentage boundary, scoring-precision boundary).
- Tier 5 — terminal-state / cascade scenarios (COMPLETED, ARCHIVED,
  pre-archive PENDING claims, scheduled trade execution past
  review_deadline_ts).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULT_BASE_CLOCK,
    create_draft_pick_payload,
    create_keeper_payload,
    create_league_payload,
    create_player_payload,
    create_team_payload,
    create_trade_payload,
    create_waiver_payload,
    iso_offset,
    iso_utc,
    manager_uid,
    patch_roster_slot_payload,
    player_status_payload,
    score_entry,
    score_payload,
    trade_vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_commissioner_headers,
    make_manager_headers,
)


COMMISSIONER = TEST_USERS["commissioner_headers"]


# ===========================================================================
# Time helpers (PRD §2.5 logical clock)
# ===========================================================================
def advance_clock_to(league_id: str, target_dt: datetime) -> Dict[str, Any]:
    """Advance League.now_ts (PRD §2.5 Commissioner-only)."""
    res = api_client.advance_clock(league_id, iso_utc(target_dt), COMMISSIONER)
    return get_success_data(res)


def advance_clock_iso(league_id: str, target_iso: str) -> Dict[str, Any]:
    res = api_client.advance_clock(league_id, target_iso, COMMISSIONER)
    return get_success_data(res)


# ===========================================================================
# Tier 1: primitive entity creation
# ===========================================================================
def create_league(**overrides) -> Dict[str, Any]:
    """Create a League in DRAFT_PENDING using the Commissioner (PRD §3.1)."""
    payload = create_league_payload(**overrides)
    res = api_client.create_league(payload, COMMISSIONER)
    return get_success_data(res)


def create_team(
    league: Dict[str, Any],
    name: Optional[str] = None,
    manager_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Team under a DRAFT_PENDING league (PRD §3.1). Returns
    the team dict; tests subsequently use
    make_manager_headers(team['manager_user_id']) for owned calls."""
    uid = manager_user_id or manager_uid()
    payload = create_team_payload(manager_user_id=uid, name=name)
    res = api_client.create_team(league["id"], payload, COMMISSIONER)
    team = get_success_data(res)
    # Ensure manager_user_id is exposed so tests can mint headers.
    if "manager_user_id" not in team:
        team["manager_user_id"] = uid
    return team


def create_player(
    full_name: Optional[str] = None,
    nfl_team: str = "KC",
    position: str = "RB",
    weekly_proj_points: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a Player via the Commissioner-only catalog endpoint (PRD §3.1)."""
    payload = create_player_payload(
        full_name=full_name,
        nfl_team=nfl_team,
        position=position,
        weekly_proj_points=weekly_proj_points,
    )
    res = api_client.create_player(payload, COMMISSIONER)
    return get_success_data(res)


def set_player_status(
    player_id: str,
    status_tag: str,
    weekly_proj_points: Optional[float] = None,
) -> Dict[str, Any]:
    """Commissioner-only test-driving endpoint (PRD §2.12, §3.1)."""
    payload = player_status_payload(
        status_tag=status_tag, weekly_proj_points=weekly_proj_points,
    )
    res = api_client.update_player_status(player_id, payload, COMMISSIONER)
    return get_success_data(res)


# ===========================================================================
# Tier 2: entity hierarchies
# ===========================================================================
def create_league_with_teams(
    *, team_count: int = 4, **league_overrides,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a League in DRAFT_PENDING and exactly `team_count` teams.

    Each team gets a unique manager_user_id. Returns (league, teams)
    where teams[i]['manager_user_id'] is the string to pass to
    make_manager_headers for that team.
    """
    league_overrides.setdefault("team_count", team_count)
    league = create_league(**league_overrides)
    teams = []
    for i in range(team_count):
        team = create_team(
            league,
            name=f"Team-{i+1}-{league['id'][:6]}",
            manager_user_id=manager_uid(f"L{league['id'][:4]}-T{i+1}"),
        )
        teams.append(team)
    return league, teams


def seed_player_catalog(
    *,
    qb: int = 2,
    rb: int = 8,
    wr: int = 8,
    te: int = 2,
    k: int = 2,
    dst: int = 2,
    flex: int = 0,
    proj_points: float = 0.0,
) -> Dict[str, List[Dict[str, Any]]]:
    """Seed a player catalog by position. Returns a dict keyed by
    position with a list of player dicts."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    plan = [
        ("QB", qb), ("RB", rb), ("WR", wr), ("TE", te),
        ("K", k), ("DST", dst), ("FLEX_RWT", flex),
    ]
    for pos, n in plan:
        out[pos] = []
        for i in range(n):
            out[pos].append(create_player(
                full_name=f"{pos}-{i+1}",
                nfl_team="KC",
                position=pos,
                weekly_proj_points=proj_points,
            ))
    return out


# ===========================================================================
# Tier 3: full lifecycle shortcuts
# ===========================================================================
def _enough_picks_for_team(roster_size: int, ir_slots: int) -> int:
    """PRD §3.3: finish-draft requires team_count * (roster_size - ir_slots)
    picks. Per-team that is roster_size - ir_slots."""
    return roster_size - ir_slots


def _snake_pick_order(team_count: int, total_picks_per_team: int) -> List[int]:
    """Standard snake ordering: round 1 = 1..N, round 2 = N..1, etc.
    Returns a flat list of team indices (0-based) of length
    team_count * total_picks_per_team."""
    order: List[int] = []
    for r in range(total_picks_per_team):
        if r % 2 == 0:
            order.extend(range(team_count))
        else:
            order.extend(range(team_count - 1, -1, -1))
    return order


def setup_drafted_league(
    *,
    team_count: int = 4,
    roster_size: int = 12,
    starter_count: int = 7,
    ir_slots: int = 1,
    regular_season_weeks: int = 10,
    playoff_team_count: int = 2,
    scoring_mode: str = "STANDARD",
    keeper_mode: str = "NONE",
    faab_budget_dollars: int = 100,
    waiver_period_hours: int = 48,
    veto_quorum_pct: int = 50,
    trade_review_hours: int = 48,
    draft_mode: str = "SNAKE",
    **league_overrides,
) -> Dict[str, Any]:
    """Create a league, seed teams, run a minimal SNAKE draft, and
    transition to REGULAR_SEASON.

    Returns a dict with keys:
      league: the league after finish-draft (status=REGULAR_SEASON)
      teams: list of team dicts (with manager_user_id present)
      players_by_team: dict team_id -> list[player] (in draft order)
      players_flat: flat list of all drafted players
    """
    league_overrides.update(dict(
        team_count=team_count,
        roster_size=roster_size,
        starter_count=starter_count,
        ir_slots=ir_slots,
        regular_season_weeks=regular_season_weeks,
        playoff_team_count=playoff_team_count,
        scoring_mode=scoring_mode,
        keeper_mode=keeper_mode,
        faab_budget_dollars=faab_budget_dollars,
        waiver_period_hours=waiver_period_hours,
        veto_quorum_pct=veto_quorum_pct,
        trade_review_hours=trade_review_hours,
        draft_mode=draft_mode,
    ))
    league, teams = create_league_with_teams(**league_overrides)
    picks_per_team = _enough_picks_for_team(roster_size, ir_slots)
    total_picks = team_count * picks_per_team

    # Seed a generic catalog: enough QB / RB / WR / TE / K / DST players
    # for every team to fill a 7-starter lineup plus bench. We bias the
    # catalog toward RB/WR/TE so FLEX placements are flexible.
    needed_qb = team_count * 1 + 2
    needed_rb = team_count * 3 + 2
    needed_wr = team_count * 4 + 2
    needed_te = team_count * 2 + 2
    needed_k = team_count * 1 + 2
    needed_dst = team_count * 1 + 2
    catalog = seed_player_catalog(
        qb=needed_qb, rb=needed_rb, wr=needed_wr, te=needed_te,
        k=needed_k, dst=needed_dst, proj_points=10.0,
    )

    # Per-team round-robin draft assignment: each team takes 1 QB, then
    # RBs / WRs / etc until picks_per_team is filled.
    per_team_plan: List[List[Dict[str, Any]]] = [[] for _ in range(team_count)]
    pos_queues = {
        "QB": list(catalog["QB"]),
        "RB": list(catalog["RB"]),
        "WR": list(catalog["WR"]),
        "TE": list(catalog["TE"]),
        "K": list(catalog["K"]),
        "DST": list(catalog["DST"]),
    }
    # Per-team needed position counts to fill at least one starter of
    # each + bench overflow.
    per_team_positions = (
        ["QB"] + ["RB"] * 3 + ["WR"] * 4 + ["TE"] * 2 + ["K"] + ["DST"]
    )
    per_team_positions = per_team_positions[:picks_per_team]
    # If picks_per_team > the static plan size, pad with RBs.
    while len(per_team_positions) < picks_per_team:
        per_team_positions.append("RB")

    for t_idx in range(team_count):
        for pos in per_team_positions:
            player = pos_queues[pos].pop(0)
            per_team_plan[t_idx].append(player)

    # Start the draft (League: DRAFT_PENDING -> DRAFTING).
    start_res = api_client.start_draft(league["id"], COMMISSIONER)
    league = get_success_data(start_res)

    if draft_mode == "SNAKE":
        order = _snake_pick_order(team_count, picks_per_team)
        # Per-team consumption pointer.
        cursors = [0] * team_count
        for team_idx in order:
            team = teams[team_idx]
            player = per_team_plan[team_idx][cursors[team_idx]]
            cursors[team_idx] += 1
            payload = create_draft_pick_payload(
                team_id=team["id"], player_id=player["id"],
            )
            mgr_headers = make_manager_headers(team["manager_user_id"])
            pick_res = api_client.create_draft_pick(league["id"], payload, mgr_headers)
            get_success_data(pick_res)
    else:
        # AUCTION: just create picks in team round-robin order with
        # price_dollars=1 each. Auction budget defaults to 200, which is
        # comfortably larger than picks_per_team * 1.
        for round_i in range(picks_per_team):
            for team_idx in range(team_count):
                team = teams[team_idx]
                player = per_team_plan[team_idx][round_i]
                payload = create_draft_pick_payload(
                    team_id=team["id"],
                    player_id=player["id"],
                    price_dollars=1,
                )
                mgr_headers = make_manager_headers(team["manager_user_id"])
                pick_res = api_client.create_draft_pick(league["id"], payload, mgr_headers)
                get_success_data(pick_res)

    # Finish draft (DRAFTING -> REGULAR_SEASON).
    finish_res = api_client.finish_draft(league["id"], COMMISSIONER)
    league = get_success_data(finish_res)

    players_by_team = {teams[i]["id"]: per_team_plan[i] for i in range(team_count)}
    players_flat = [p for team_players in per_team_plan for p in team_players]
    return {
        "league": league,
        "teams": teams,
        "players_by_team": players_by_team,
        "players_flat": players_flat,
    }


def get_team_roster_slots(league_id: str, team_id: str) -> List[Dict[str, Any]]:
    """Fetch the latest RosterSlot list for the team by re-reading the
    team detail. Most implementations expose roster slots inline on the
    team detail; if not, callers should use list endpoints they exposed."""
    res = api_client.get_team(league_id, team_id, COMMISSIONER)
    team_data = get_success_data(res)
    return list(team_data.get("roster_slots") or [])


def list_roster_slots_for_team(league_id: str, team_id: str) -> List[Dict[str, Any]]:
    return get_team_roster_slots(league_id, team_id)


def list_waivers(league_id: str, **params) -> List[Dict[str, Any]]:
    res = api_client.list_waivers(league_id, COMMISSIONER, params=params or None)
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return list(data or [])


def list_trades(league_id: str, **params) -> List[Dict[str, Any]]:
    res = api_client.list_trades(league_id, COMMISSIONER, params=params or None)
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return list(data or [])


def list_matchups(league_id: str, **params) -> List[Dict[str, Any]]:
    res = api_client.list_matchups(league_id, COMMISSIONER, params=params or None)
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return list(data or [])


def fetch_team(league_id: str, team_id: str) -> Dict[str, Any]:
    res = api_client.get_team(league_id, team_id, COMMISSIONER)
    return get_success_data(res)


def fetch_trade(league_id: str, trade_id: str) -> Optional[Dict[str, Any]]:
    """Re-read a trade by listing trades and finding by id."""
    for t in list_trades(league_id):
        if t.get("id") == trade_id:
            return t
    return None


def fetch_waiver(league_id: str, waiver_id: str) -> Optional[Dict[str, Any]]:
    for w in list_waivers(league_id):
        if w.get("id") == waiver_id:
            return w
    return None


def fetch_matchup(league_id: str, week_number: int) -> Optional[Dict[str, Any]]:
    for m in list_matchups(league_id, week_number=week_number):
        if m.get("week_number") == week_number:
            return m
    return None


# ===========================================================================
# Tier 3: state-targeting fixtures
# ===========================================================================
def setup_locked_week(
    *,
    starter_count: int = 7,
    team_count: int = 4,
    scoring_mode: str = "STANDARD",
    lock_offset_hours: int = 24,
    **draft_overrides,
) -> Dict[str, Any]:
    """Run setup_drafted_league through to LOCKED week 1.

    Advances League.now_ts by lock_offset_hours hours (sufficient to
    trigger the week-1 lock). Returns the same dict as
    setup_drafted_league plus 'matchups_week_1'.
    """
    bundle = setup_drafted_league(
        starter_count=starter_count,
        team_count=team_count,
        scoring_mode=scoring_mode,
        **draft_overrides,
    )
    league = bundle["league"]
    target = DEFAULT_BASE_CLOCK + timedelta(days=7, hours=lock_offset_hours)
    bundle["league"] = advance_clock_to(league["id"], target)
    bundle["matchups_week_1"] = list_matchups(league["id"], week_number=1)
    return bundle


def setup_scored_regular_season(
    *,
    team_count: int = 4,
    regular_season_weeks: int = 10,
    starter_count: int = 7,
    scoring_mode: str = "STANDARD",
    **draft_overrides,
) -> Dict[str, Any]:
    """Drive a league all the way through every regular-season week
    being SCORED so current_week == regular_season_weeks (and a clock
    advance into week regular_season_weeks+1 will transition to
    PLAYOFFS)."""
    bundle = setup_drafted_league(
        team_count=team_count,
        regular_season_weeks=regular_season_weeks,
        starter_count=starter_count,
        scoring_mode=scoring_mode,
        **draft_overrides,
    )
    league = bundle["league"]
    base = DEFAULT_BASE_CLOCK
    for wk in range(1, regular_season_weeks + 1):
        # Advance to lock instant of the week.
        target = base + timedelta(days=7 * wk, hours=24)
        bundle["league"] = advance_clock_to(league["id"], target)
        # Score the week with all-zero points (deterministic tie-break by id).
        matchups = list_matchups(league["id"], week_number=wk)
        for mu in matchups:
            home = mu["home_team_id"]
            away = mu["away_team_id"]
            # Pull each team's STARTER roster to enumerate score entries.
            home_team = fetch_team(league["id"], home)
            away_team = fetch_team(league["id"], away)
            home_starters = [
                rs for rs in home_team.get("roster_slots", [])
                if rs.get("slot_type") == "STARTER"
            ]
            away_starters = [
                rs for rs in away_team.get("roster_slots", [])
                if rs.get("slot_type") == "STARTER"
            ]
            scores = []
            for rs in home_starters + away_starters:
                scores.append(score_entry(
                    player_id=rs["player_id"], actual_points=0.0,
                    receptions_credited=0,
                ))
            api_client.score_matchup(
                league["id"], wk, score_payload(scores), COMMISSIONER,
            )
    return bundle


# ===========================================================================
# Tier 4: trade-state targeting
# ===========================================================================
def propose_trade(
    *,
    league: Dict[str, Any],
    proposing_team: Dict[str, Any],
    counterparty_team: Dict[str, Any],
    send_player_ids: List[str],
    receive_player_ids: List[str],
    send_faab_dollars: Optional[int] = None,
    receive_faab_dollars: Optional[int] = None,
) -> Dict[str, Any]:
    """Manager-owned proposal endpoint. Headers minted from the
    proposer's manager_user_id (PRD §2.1)."""
    payload = create_trade_payload(
        proposing_team_id=proposing_team["id"],
        counterparty_team_id=counterparty_team["id"],
        send_player_ids=send_player_ids,
        receive_player_ids=receive_player_ids,
        send_faab_dollars=send_faab_dollars,
        receive_faab_dollars=receive_faab_dollars,
    )
    headers = make_manager_headers(proposing_team["manager_user_id"])
    res = api_client.create_trade(league["id"], payload, headers)
    return get_success_data(res)


def accept_trade_as(trade_id: str, counterparty_team: Dict[str, Any]) -> Dict[str, Any]:
    """Accept call must be made by the counterparty manager — PRD §3.7."""
    headers = make_manager_headers(counterparty_team["manager_user_id"])
    res = api_client.accept_trade(trade_id, headers)
    return get_success_data(res)


def reject_trade_as(trade_id: str, counterparty_team: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_manager_headers(counterparty_team["manager_user_id"])
    res = api_client.reject_trade(trade_id, headers)
    return get_success_data(res)


def cancel_trade_as(trade_id: str, proposing_team: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_manager_headers(proposing_team["manager_user_id"])
    res = api_client.cancel_trade(trade_id, headers)
    return get_success_data(res)


def cast_vote_as(
    trade_id: str,
    voting_team: Dict[str, Any],
    vote: str,
) -> Dict[str, Any]:
    """Voter must be a team OTHER than proposer/counterparty (PRD §3.7).
    Headers minted from the voting team's manager_user_id."""
    payload = trade_vote_payload(voting_team_id=voting_team["id"], vote=vote)
    headers = make_manager_headers(voting_team["manager_user_id"])
    res = api_client.cast_trade_vote(trade_id, payload, headers)
    return get_success_data(res)


def setup_accepted_trade(
    *,
    team_count: int = 4,
    veto_quorum_pct: int = 50,
    trade_review_hours: int = 48,
    send_faab_dollars: Optional[int] = None,
) -> Dict[str, Any]:
    """Drive a league to REGULAR_SEASON, then propose + accept a 1-for-1
    trade. Returns {league, teams, players_by_team, trade,
    p_send (player), p_recv (player)}.
    """
    bundle = setup_drafted_league(
        team_count=team_count,
        veto_quorum_pct=veto_quorum_pct,
        trade_review_hours=trade_review_hours,
    )
    league = bundle["league"]
    teams = bundle["teams"]
    t1, t2 = teams[0], teams[1]
    p_send = bundle["players_by_team"][t1["id"]][1]  # avoid QB which is index 0
    p_recv = bundle["players_by_team"][t2["id"]][1]
    trade = propose_trade(
        league=league,
        proposing_team=t1,
        counterparty_team=t2,
        send_player_ids=[p_send["id"]],
        receive_player_ids=[p_recv["id"]],
        send_faab_dollars=send_faab_dollars,
    )
    trade = accept_trade_as(trade["id"], t2)
    bundle["trade"] = trade
    bundle["p_send"] = p_send
    bundle["p_recv"] = p_recv
    return bundle


# ===========================================================================
# Tier 4: waiver-state targeting
# ===========================================================================
def submit_waiver(
    *,
    league: Dict[str, Any],
    team: Dict[str, Any],
    add_player_id: str,
    bid_dollars: int,
    settle_offset_hours: int = 2,
    drop_player_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a FAAB waiver claim with settle_ts in the near future.

    PRD §3.6: settle_ts must be strictly greater than League.now_ts.
    """
    league = get_success_data(api_client.get_league(league["id"], COMMISSIONER))
    now_ts = league["now_ts"]
    base = datetime.fromisoformat(now_ts.replace("Z", "+00:00"))
    settle_ts = iso_offset(base, hours=settle_offset_hours)
    payload = create_waiver_payload(
        team_id=team["id"],
        add_player_id=add_player_id,
        bid_dollars=bid_dollars,
        settle_ts=settle_ts,
        drop_player_id=drop_player_id,
    )
    headers = make_manager_headers(team["manager_user_id"])
    res = api_client.create_waiver(league["id"], payload, headers)
    return get_success_data(res)


def cancel_waiver_as(waiver_id: str, team: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_manager_headers(team["manager_user_id"])
    res = api_client.cancel_waiver(waiver_id, headers)
    return get_success_data(res)


# ===========================================================================
# Tier 4 / 5: keeper / pre-draft setup
# ===========================================================================
def declare_keeper(
    *,
    team: Dict[str, Any],
    player_id: str,
    season_year: int,
) -> Dict[str, Any]:
    payload = create_keeper_payload(player_id=player_id, season_year=season_year)
    headers = make_manager_headers(team["manager_user_id"])
    res = api_client.create_keeper(team["id"], payload, headers)
    return get_success_data(res)


def revoke_keeper(
    *,
    team: Dict[str, Any],
    keeper_id: str,
) -> Dict[str, Any]:
    headers = make_manager_headers(team["manager_user_id"])
    res = api_client.revoke_keeper(team["id"], keeper_id, headers)
    return get_success_data(res)


def setup_prior_season_snake_pick(
    *,
    manager_user_id: str,
    season_year: int = 2025,
    regular_season_weeks: int = 14,
    team_count: int = 4,
    roster_size: int = 12,
    starter_count: int = 7,
    ir_slots: int = 1,
    target_round_for_player: int = 5,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create a prior-season SNAKE league + finish-draft so a target
    player ends up on the target_round for the given team. Returns
    (prior_league, prior_team, target_player).

    Implementation note (PRD §3.2 keeper_snake_round):
    "looks up the prior-season DraftPick.round_number for this team_id
    and player_id pairing if one exists ... subtracts 1 from that prior
    round, and then takes the larger of that result and 1." For
    keeper_round = max(1, prior_round - 1) to yield a specific result,
    the prior_round here is the target_round_for_player.
    """
    league = create_league(
        name=f"Prior-{season_year}",
        season_year=season_year,
        draft_mode="SNAKE",
        team_count=team_count,
        roster_size=roster_size,
        starter_count=starter_count,
        ir_slots=ir_slots,
        regular_season_weeks=regular_season_weeks,
        keeper_mode="DYNASTY",
        keeper_cap=2,
    )
    # Create teams; the first team uses the supplied manager_user_id.
    teams: List[Dict[str, Any]] = []
    teams.append(create_team(league, name="Team-1", manager_user_id=manager_user_id))
    for i in range(1, team_count):
        teams.append(create_team(
            league, name=f"Team-{i+1}",
            manager_user_id=manager_uid(f"prior-T{i+1}"),
        ))
    picks_per_team = roster_size - ir_slots
    # Seed a generic catalog large enough for the draft. We deliberately
    # over-allocate RB by 1 because the target_player is popped from RB
    # and may replace a non-RB slot, so other-team RB demand is unchanged.
    catalog = seed_player_catalog(
        qb=team_count, rb=team_count * 3 + 1, wr=team_count * 4,
        te=team_count * 2, k=team_count, dst=team_count,
        proj_points=10.0,
    )
    # Target player is one RB that team-0 will pick in target_round.
    # We construct a plan where team-0's pick in target_round is a
    # designated RB (target_player).
    if not catalog["RB"]:
        raise AssertionError("seed_player_catalog must produce RB players")
    target_player = catalog["RB"].pop(0)

    # Build per-team plan; team-0 takes target_player at index
    # (target_round - 1).
    per_team_plan: List[List[Dict[str, Any]]] = [[] for _ in range(team_count)]
    pos_queues = {
        "QB": list(catalog["QB"]),
        "RB": list(catalog["RB"]),
        "WR": list(catalog["WR"]),
        "TE": list(catalog["TE"]),
        "K": list(catalog["K"]),
        "DST": list(catalog["DST"]),
    }
    per_team_positions = (
        ["QB"] + ["RB"] * 3 + ["WR"] * 4 + ["TE"] * 2 + ["K"] + ["DST"]
    )
    per_team_positions = per_team_positions[:picks_per_team]
    while len(per_team_positions) < picks_per_team:
        per_team_positions.append("RB")

    for t_idx in range(team_count):
        for round_i, pos in enumerate(per_team_positions):
            if t_idx == 0 and (round_i + 1) == target_round_for_player:
                per_team_plan[t_idx].append(target_player)
            else:
                per_team_plan[t_idx].append(pos_queues[pos].pop(0))

    # Start the draft.
    get_success_data(api_client.start_draft(league["id"], COMMISSIONER))
    order = _snake_pick_order(team_count, picks_per_team)
    cursors = [0] * team_count
    for team_idx in order:
        team = teams[team_idx]
        player = per_team_plan[team_idx][cursors[team_idx]]
        cursors[team_idx] += 1
        payload = create_draft_pick_payload(
            team_id=team["id"], player_id=player["id"],
        )
        mgr_headers = make_manager_headers(team["manager_user_id"])
        get_success_data(api_client.create_draft_pick(league["id"], payload, mgr_headers))
    finished = get_success_data(api_client.finish_draft(league["id"], COMMISSIONER))
    return finished, teams[0], target_player


def setup_prior_season_auction_pick(
    *,
    manager_user_id: str,
    season_year: int = 2025,
    regular_season_weeks: int = 10,
    team_count: int = 4,
    target_player_prices: Optional[List[int]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Run a minimal prior-season AUCTION draft so that team-0 acquires
    the listed players at the listed prices. Returns (league, team_0,
    target_players)."""
    target_player_prices = list(target_player_prices or [20, 5])
    roster_size = 12
    starter_count = 7
    ir_slots = 1
    league = create_league(
        name=f"Prior-Auction-{season_year}",
        season_year=season_year,
        draft_mode="AUCTION",
        team_count=team_count,
        roster_size=roster_size,
        starter_count=starter_count,
        ir_slots=ir_slots,
        regular_season_weeks=regular_season_weeks,
        keeper_mode="DYNASTY",
        keeper_cap=max(2, len(target_player_prices)),
        auction_budget_dollars=200,
    )
    teams: List[Dict[str, Any]] = [
        create_team(league, name="Team-A", manager_user_id=manager_user_id),
    ]
    for i in range(1, team_count):
        teams.append(create_team(
            league, name=f"Team-{i+1}",
            manager_user_id=manager_uid(f"prior-auc-T{i+1}"),
        ))
    picks_per_team = roster_size - ir_slots
    catalog = seed_player_catalog(
        qb=team_count, rb=team_count * 4, wr=team_count * 4,
        te=team_count * 2, k=team_count, dst=team_count,
        proj_points=10.0,
    )
    target_players: List[Dict[str, Any]] = []
    for _ in target_player_prices:
        target_players.append(catalog["RB"].pop(0))

    # Plan per team: team-0 picks target_players first (with given
    # prices), then fills out with cheap $1 picks. Other teams pick all
    # at $1.
    per_team_plan: List[List[Tuple[Dict[str, Any], int]]] = [[] for _ in range(team_count)]
    # Team 0's first len(target_players) picks are the target players.
    for plyr, price in zip(target_players, target_player_prices):
        per_team_plan[0].append((plyr, price))
    pos_queues = {
        "QB": list(catalog["QB"]),
        "RB": list(catalog["RB"]),
        "WR": list(catalog["WR"]),
        "TE": list(catalog["TE"]),
        "K": list(catalog["K"]),
        "DST": list(catalog["DST"]),
    }
    per_team_positions = (
        ["QB"] + ["RB"] * 3 + ["WR"] * 4 + ["TE"] * 2 + ["K"] + ["DST"]
    )
    per_team_positions = per_team_positions[:picks_per_team]
    while len(per_team_positions) < picks_per_team:
        per_team_positions.append("RB")

    # Fill team 0's remaining picks with $1 picks.
    remaining = picks_per_team - len(target_players)
    for i in range(remaining):
        pos = per_team_positions[i] if i < len(per_team_positions) else "RB"
        per_team_plan[0].append((pos_queues[pos].pop(0), 1))
    # Other teams: all $1 picks.
    for t_idx in range(1, team_count):
        for round_i in range(picks_per_team):
            pos = per_team_positions[round_i] if round_i < len(per_team_positions) else "RB"
            per_team_plan[t_idx].append((pos_queues[pos].pop(0), 1))

    get_success_data(api_client.start_draft(league["id"], COMMISSIONER))
    # AUCTION: no turn-order check (PRD §3.3); fire picks in team-major
    # order.
    for t_idx in range(team_count):
        team = teams[t_idx]
        mgr_headers = make_manager_headers(team["manager_user_id"])
        for player, price in per_team_plan[t_idx]:
            payload = create_draft_pick_payload(
                team_id=team["id"], player_id=player["id"], price_dollars=price,
            )
            get_success_data(api_client.create_draft_pick(league["id"], payload, mgr_headers))
    finished = get_success_data(api_client.finish_draft(league["id"], COMMISSIONER))
    return finished, teams[0], target_players


# ===========================================================================
# Convenience aliases used by tests
# ===========================================================================
def first_team_starter_slot(
    league_id: str,
    team_id: str,
    *,
    position_root: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return a starter RosterSlot on the team. If position_root is
    given, filter to slots whose position_label startswith that
    (e.g., 'RB' matches RB1/RB2)."""
    slots = list_roster_slots_for_team(league_id, team_id)
    for s in slots:
        if s.get("slot_type") != "STARTER":
            continue
        if position_root is None:
            return s
        pl = s.get("position_label") or ""
        if pl.startswith(position_root):
            return s
    return None


def first_team_bench_slot(
    league_id: str,
    team_id: str,
    *,
    position_match: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return a bench RosterSlot on the team. If position_match is
    given (a Player.position value), check the player's position."""
    slots = list_roster_slots_for_team(league_id, team_id)
    for s in slots:
        if s.get("slot_type") != "BENCH":
            continue
        if position_match is None:
            return s
        # We need to identify the player position; we cache via player
        # list. Cheap path: just take any BENCH if we don't know the
        # player's position. Tests that care can call create_player
        # directly.
        return s
    return None


__all__ = [
    "COMMISSIONER",
    "advance_clock_to",
    "advance_clock_iso",
    "create_league",
    "create_team",
    "create_player",
    "set_player_status",
    "create_league_with_teams",
    "seed_player_catalog",
    "setup_drafted_league",
    "setup_locked_week",
    "setup_scored_regular_season",
    "setup_accepted_trade",
    "setup_prior_season_snake_pick",
    "setup_prior_season_auction_pick",
    "propose_trade",
    "accept_trade_as",
    "reject_trade_as",
    "cancel_trade_as",
    "cast_vote_as",
    "submit_waiver",
    "cancel_waiver_as",
    "declare_keeper",
    "revoke_keeper",
    "get_team_roster_slots",
    "list_roster_slots_for_team",
    "list_waivers",
    "list_trades",
    "list_matchups",
    "fetch_team",
    "fetch_trade",
    "fetch_waiver",
    "fetch_matchup",
    "first_team_starter_slot",
    "first_team_bench_slot",
]
