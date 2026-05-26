"""All calculation rules: draft_pick_value, team_playoff_seed,
waiver_priority_resolution, dynasty_keeper_cost, injury_replacement_projection,
trade_fairness_score.

Monetary / score calculations all use Decimal with ROUND_HALF_UP per PRD §2.6.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from db import store


# ---------------- Rounding helper ----------------

def round_half_up(value, places: int) -> float:
    """Round `value` half-up to `places` decimals, returning a float."""
    if value is None:
        return 0.0
    q = Decimal(10) ** -places
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(d)


INJURY_PENALTY = 4.0
KEEPER_FLOOR_ROUND = 1


# ---------------- Draft pick valuation ----------------

def draft_pick_value(league: dict, player: dict) -> dict:
    """Return {"value": ..., "variant": "snake" | "auction"}."""
    if league["draft_type"] == "SNAKE":
        val = round_half_up(
            float(player["projected_points"]) - float(player["replacement_value"]),
            2,
        )
        return {"value": val, "variant": "snake"}

    if league["draft_type"] == "AUCTION":
        # Build top pool: all players ordered by projected_points DESC,
        # ties broken by created_at ASC (never id), limited to
        # roster_size * team_count.
        team_count = sum(
            1 for t in store().teams.values() if t["league_id"] == league["id"]
        )
        pool_size = league["roster_size"] * team_count
        all_players = sorted(
            store().players.values(),
            key=lambda p: (-float(p["projected_points"]), p["created_at"], p.get("_seq", 0)),
        )
        top_pool = all_players[:pool_size]
        total_pp = sum(float(p["projected_points"]) for p in top_pool)
        share = 0.0 if total_pp == 0 else float(player["projected_points"]) / total_pp
        val = round_half_up((league["faab_budget_cents"] / 100.0) * share, 2)
        return {"value": val, "variant": "auction"}

    return {"value": 0.0, "variant": "snake"}


# ---------------- Playoff seeding ----------------

def compute_playoff_seeds(league: dict) -> list[dict]:
    """Return teams in seeded order; assign `playoff_seed` 1..N to top N teams."""
    teams = [t for t in store().teams.values() if t["league_id"] == league["id"]]
    rule = league["tiebreak_rule"]
    if rule == "STANDARD":
        teams.sort(key=lambda t: (
            -int(t["wins"]),
            -float(t["total_points_for"]),
            t["created_at"],
            t.get("_seq", 0),
        ))
    elif rule == "DIVISION_FIRST":
        teams.sort(key=lambda t: (
            -int(t["wins"]),
            -int(t["intra_division_wins"]),
            -float(t["total_points_for"]),
            t["created_at"],
            t.get("_seq", 0),
        ))
    N = league["playoff_team_count"]
    for idx, team in enumerate(teams):
        team["playoff_seed"] = idx + 1 if idx < N else 0
    return teams


# ---------------- Dynasty keeper cost ----------------

def recompute_keeper_costs(team: dict) -> None:
    """Recompute keeper_round on each keeper's latest DraftPick row.

    Walk team.keeper_player_ids in Player.created_at ASC order.
    For idx-th keeper (0-indexed): cost = max(1, original_round - idx).
    """
    keeper_ids = list(team.get("keeper_player_ids") or [])
    if not keeper_ids:
        return
    # Sort by Player.created_at ASC.
    players = []
    for pid in keeper_ids:
        p = store().players.get(pid)
        if p is None:
            continue
        players.append(p)
    players.sort(key=lambda p: (p["created_at"], p.get("_seq", 0)))
    for idx, p in enumerate(players):
        # Latest DraftPick row for (team, player) in this league.
        picks = [
            dp for dp in store().draft_picks.values()
            if dp["team_id"] == team["id"] and dp["player_id"] == p["id"]
        ]
        if not picks:
            continue
        picks.sort(key=lambda dp: (dp["created_at"], dp.get("_seq", 0)))
        latest = picks[-1]
        original_round = int(latest["round"])
        new_round = max(KEEPER_FLOOR_ROUND, original_round - idx)
        latest["keeper_round"] = new_round
        latest["is_keeper"] = True
        # No version bump for DraftPick per spec (DraftPick has no version
        # field listed for OCC) — but bump for consistency since it has
        # common_fields.
        from services.common import bump
        bump(latest)


# ---------------- Injury replacement projection ----------------

def injury_replacement_projection_for_team(team_id: str, week: int) -> float:
    """Compute team's locked-STARTER score under §3.6.

    Per-line round to 2 decimals, sum, then round sum again to 2 decimals.
    Player status sampled at finalize time.
    """
    slots = [
        s for s in store().roster_slots.values()
        if s["team_id"] == team_id
        and s["slot_type"] == "STARTER"
        and int(s.get("week_locked", 0)) == int(week)
    ]
    line_items = []
    for s in slots:
        p = store().players.get(s["player_id"])
        if p is None:
            continue
        base = float(p.get("projected_points", 0))
        status = p["status"]
        if status == "ACTIVE":
            adjusted = base
        elif status == "INJURED":
            adjusted = max(0.0, base - INJURY_PENALTY)
        elif status == "IR_PLACED":
            adjusted = 0.0
        else:
            adjusted = 0.0
        line_items.append(round_half_up(adjusted, 2))
    total = sum(line_items)
    return round_half_up(total, 2)


# ---------------- Trade fairness ----------------

def trade_fairness(trade: dict) -> dict:
    """Per-player round to 1 decimal -> sum -> round to 2 decimals.

    fairness_score = round(abs((offered_value + faab_delta) - requested_value), 2)
    """
    def side_value(player_ids):
        rounded = []
        for pid in player_ids:
            p = store().players.get(pid)
            if p is None:
                continue
            rounded.append(round_half_up(float(p.get("projected_points", 0)), 1))
        s = sum(rounded)
        return round_half_up(s, 2)

    offered_value = side_value(trade.get("players_offered") or [])
    requested_value = side_value(trade.get("players_requested") or [])
    faab_delta = float(trade.get("faab_offered_cents", 0)) / 100.0
    fairness = round_half_up(
        abs((offered_value + faab_delta) - requested_value), 2
    )
    return {
        "fairness_score": fairness,
        "offered_value": offered_value,
        "requested_value": requested_value,
    }


# ---------------- Waiver priority resolution ----------------

def resolve_waiver_batch(league: dict):
    """Resolve all SUBMITTED claims for league.current_week. Pass 1, 2, 3."""
    from services.common import bump

    current_week = int(league["current_week"])

    # All candidate claims in this league for this week.
    candidates = [
        c for c in store().waiver_claims.values()
        if c["league_id"] == league["id"]
        and c["state"] == "SUBMITTED"
        and int(c["processing_week"]) == current_week
    ]
    # Sort all candidates by created_at ASC for deterministic processing.
    candidates.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))

    # Pass 1: mark INVALID any claim where the target player is RELEASED or
    # the team's faab_balance_cents < bid_cents.
    survivors = []
    for c in candidates:
        player = store().players.get(c["player_id"])
        team = store().teams.get(c["team_id"])
        if player is None or team is None:
            c["state"] = "INVALID"
            bump(c)
            continue
        if player["status"] == "RELEASED":
            c["state"] = "INVALID"
            bump(c)
            continue
        if int(team["faab_balance_cents"]) < int(c["bid_cents"]):
            c["state"] = "INVALID"
            bump(c)
            continue
        survivors.append(c)

    # Pass 2: group by player_id, pick winner per group; commit in
    # created_at order across groups. Same-team FAAB-drain triggers
    # cascade INVALIDATION for that team's remaining claims this week.
    # Build groups.
    by_player: dict[str, list] = {}
    for c in survivors:
        by_player.setdefault(c["player_id"], []).append(c)

    # Decide per-group winners (sort by bid_cents DESC, priority_at_submission
    # ASC, created_at ASC).
    winners_set: set[str] = set()
    for pid, group in by_player.items():
        group_sorted = sorted(
            group,
            key=lambda c: (
                -int(c["bid_cents"]),
                int(c["priority_at_submission"]),
                c["created_at"],
                c.get("_seq", 0),
            ),
        )
        winners_set.add(group_sorted[0]["id"])

    # Process winners in created_at ASC order across groups.
    winner_claims = [c for c in survivors if c["id"] in winners_set]
    winner_claims.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))

    drained_teams: set[str] = set()
    losers_to_mark = []

    # Cache: remember for each team the set of competing claims to mark as LOST_BID later
    for c in winner_claims:
        team = store().teams[c["team_id"]]
        player = store().players[c["player_id"]]
        # Pre-commit checks: team still has enough FAAB, team not already drained.
        if team["id"] in drained_teams:
            c["state"] = "INVALID"
            bump(c)
            continue
        if int(team["faab_balance_cents"]) < int(c["bid_cents"]):
            c["state"] = "INVALID"
            bump(c)
            continue
        # Player must still be in ACTIVE, INJURED, IR_PLACED.
        if player["status"] not in {"ACTIVE", "INJURED", "IR_PLACED"}:
            c["state"] = "INVALID"
            bump(c)
            continue
        # If player has a current_team_id, drop_player_id must be supplied OR
        # we should still allow it (PRD says "current_team_id is null OR
        # drop_player_id is supplied"). If neither, mark invalid.
        if player.get("current_team_id") is not None and not c.get("drop_player_id"):
            c["state"] = "INVALID"
            bump(c)
            continue

        # Apply WON side effects.
        # 1) Debit FAAB.
        team["faab_balance_cents"] = int(team["faab_balance_cents"]) - int(c["bid_cents"])
        # 2) Move player to this team; create BENCH RosterSlot.
        from services.roster import (
            create_roster_slot,
            delete_roster_slots_for,
        )
        player["current_team_id"] = team["id"]
        bump(player)
        # If drop_player_id provided: delete that slot; null its current_team_id.
        if c.get("drop_player_id"):
            drop_pid = c["drop_player_id"]
            delete_roster_slots_for(team["id"], drop_pid)
            drop_player = store().players.get(drop_pid)
            if drop_player is not None:
                drop_player["current_team_id"] = None
                bump(drop_player)
        # If player already had a current_team_id (i.e., on another team)
        # remove their old roster slots.
        # (Note: tests should free the player via release first, but be safe.)
        for slot_id, slot in list(store().roster_slots.items()):
            if slot["player_id"] == player["id"] and slot["team_id"] != team["id"]:
                del store().roster_slots[slot_id]
        create_roster_slot(team_id=team["id"], player_id=player["id"], slot_type="BENCH")
        # 3) Rotate waiver_priority: this team -> highest number (lowest priority).
        rotate_waiver_priority_reverse_robin(c["league_id"], team["id"])
        # 4) Claim WON.
        c["state"] = "WON"
        bump(c)
        bump(team)
        # 5) Cascade-INVALIDATE: if team faab now 0, mark remaining same-team
        # SUBMITTED claims in this week as INVALID.
        if int(team["faab_balance_cents"]) == 0:
            drained_teams.add(team["id"])
            for other in survivors:
                if (
                    other["id"] != c["id"]
                    and other["team_id"] == team["id"]
                    and other["state"] == "SUBMITTED"
                ):
                    other["state"] = "INVALID"
                    bump(other)

    # Pass 3: any remaining SUBMITTED loser (non-winner) gets LOST_BID.
    for c in survivors:
        if c["state"] == "SUBMITTED":
            c["state"] = "LOST_BID"
            bump(c)


def rotate_waiver_priority_reverse_robin(league_id: str, winning_team_id: str):
    """Move the winning team to the lowest waiver priority (highest number)
    and shift everyone else who was below the winner up by one.
    """
    teams = [t for t in store().teams.values() if t["league_id"] == league_id]
    teams.sort(key=lambda t: int(t.get("waiver_priority", 0)))
    winner = next((t for t in teams if t["id"] == winning_team_id), None)
    if winner is None:
        return
    winning_priority = int(winner["waiver_priority"])
    # Decrement priority for all teams with priority > winner's priority.
    for t in teams:
        wp = int(t.get("waiver_priority", 0))
        if wp > winning_priority:
            t["waiver_priority"] = wp - 1
    # Place winner at the highest number.
    winner["waiver_priority"] = len(teams)
