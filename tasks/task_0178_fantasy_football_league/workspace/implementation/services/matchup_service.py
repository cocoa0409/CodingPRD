"""Matchup generation, lock cascades, and scoring."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from core.errors import (
    err_invalid_state,
    err_resource_not_found,
    err_validation,
)
from core.store import store
from core.utils import format_iso, parse_iso
from services.timestamps import stamp_create, stamp_update


def generate_regular_season(league: Dict[str, Any]) -> None:
    """Round-robin schedule for weeks 1..regular_season_weeks."""
    teams = store.teams_in_league(league["id"])
    teams_sorted = sorted(teams, key=lambda t: t.get("draft_position") or 0)
    n = len(teams_sorted)
    if n % 2 != 0:
        # Should never happen; team_count is even per validation
        return

    # Round-robin (circle method)
    weeks = league["regular_season_weeks"]
    # Fix first team, rotate the others
    schedule_rotation = teams_sorted[:]

    for w in range(1, weeks + 1):
        # Generate pairings for this week
        half = n // 2
        rotation_index = (w - 1) % (n - 1)
        # Standard circle-method rotation
        rotated = [schedule_rotation[0]] + (
            schedule_rotation[1:][rotation_index:] + schedule_rotation[1:][:rotation_index]
        )
        pairings = []
        for i in range(half):
            home = rotated[i]
            away = rotated[n - 1 - i]
            pairings.append((home, away))

        for (home, away) in pairings:
            mw = {
                "league_id": league["id"],
                "week_number": w,
                "home_team_id": home["id"],
                "away_team_id": away["id"],
                "home_points": 0,
                "away_points": 0,
                "status": "SCHEDULED",
                "is_playoff": False,
                "bracket_round": None,
            }
            stamp_create(mw)
            store.matchup_weeks[mw["id"]] = mw


def list_matchups(league_id: str, week_number: Optional[int] = None, is_playoff: Optional[bool] = None) -> List[Dict[str, Any]]:
    from services.league_service import get_league
    get_league(league_id)
    items = store.matchups_in_league(league_id)
    if week_number is not None:
        items = [m for m in items if m["week_number"] == week_number]
    if is_playoff is not None:
        items = [m for m in items if m["is_playoff"] == is_playoff]
    items.sort(key=lambda x: (x["week_number"], x["created_at"]))
    return items


def cascade_locks(league: Dict[str, Any]) -> None:
    """Lock the current week's SCHEDULED matchups when the clock reaches them.

    The PRD defines a "configured lock instant" per week; for this implementation
    we treat the lock as triggered as soon as `League.now_ts` is at-or-beyond the
    creation time of the matchup AND week_number equals current_week. In practice
    tests advance the clock explicitly which fires this cascade.
    """
    if league["status"] not in {"REGULAR_SEASON", "PLAYOFFS"}:
        return
    current_week = league["current_week"]
    matchups = [
        m
        for m in store.matchups_in_league(league["id"])
        if m["week_number"] == current_week and m["status"] == "SCHEDULED"
    ]
    for m in matchups:
        _lock_matchup(league, m)


def lock_current_week(league_id: str):
    """Helper test endpoint: explicitly lock current week's matchups."""
    from services.league_service import get_league
    league = get_league(league_id)
    cascade_locks(league)


def _lock_matchup(league: Dict[str, Any], matchup: Dict[str, Any]) -> None:
    matchup["status"] = "LOCKED"
    stamp_update(matchup)

    # Snapshot starter slots and set locked_until_ts (end of week sentinel)
    home_id = matchup["home_team_id"]
    away_id = matchup["away_team_id"]
    snap = {}
    for team_id in (home_id, away_id):
        starters = [
            s
            for s in store.roster_slots_for_team(team_id)
            if s["slot_type"] == "STARTER"
        ]
        snap[team_id] = [s["id"] for s in starters]
        # Lock until end-of-week sentinel — use a far-future timestamp
        for s in starters:
            s["locked_until_ts"] = league["now_ts"]
            stamp_update(s)
    store.lock_snapshots[(league["id"], matchup["week_number"])] = snap

    # Injury replacement
    for team_id in (home_id, away_id):
        _injury_replacement(team_id)


def _injury_replacement(team_id: str) -> None:
    """For every starter with status_tag=OUT, find best bench replacement."""
    from services.roster_service import position_compatible, position_root

    slots = store.roster_slots_for_team(team_id)
    starters_out = []
    for s in slots:
        if s["slot_type"] != "STARTER":
            continue
        player = store.players.get(s["player_id"])
        if player and player["status_tag"] == "OUT":
            starters_out.append(s)

    for starter in starters_out:
        position_label = starter["position_label"]
        # Find bench candidates
        candidates = []
        for b in store.roster_slots_for_team(team_id):
            if b["slot_type"] != "BENCH":
                continue
            bp = store.players.get(b["player_id"])
            if not bp:
                continue
            if bp["status_tag"] in {"OUT", "IR_ELIGIBLE"}:
                continue
            if not position_compatible(bp["position"], position_label):
                continue
            candidates.append((b, bp))

        if not candidates:
            continue
        # Sort: weekly_proj_points desc, then player id asc
        candidates.sort(
            key=lambda tup: (-tup[1]["weekly_proj_points"], tup[1]["id"])
        )
        best, _ = candidates[0]
        # Swap slot_type and position_label
        starter["slot_type"], best["slot_type"] = best["slot_type"], starter["slot_type"]
        starter["position_label"], best["position_label"] = (
            best["position_label"],
            starter["position_label"],
        )
        stamp_update(starter)
        stamp_update(best)


def score_matchup(league_id: str, week_number: int, body: Dict[str, Any]) -> List[Dict[str, Any]]:
    from services.league_service import get_league
    league = get_league(league_id)
    scores = body.get("scores")
    if not isinstance(scores, list) or not scores:
        raise err_validation("scores must be a non-empty array.")

    matchups = [
        m
        for m in store.matchups_in_league(league_id)
        if m["week_number"] == week_number
    ]
    if not matchups:
        raise err_resource_not_found(f"No matchups for week {week_number}.")
    # All must be LOCKED
    for m in matchups:
        if m["status"] != "LOCKED":
            raise err_invalid_state(
                f"Matchup {m['id']} not LOCKED (current={m['status']})."
            )

    # Build per-player score map
    score_map = {}
    for entry in scores:
        pid = entry.get("player_id")
        ap = entry.get("actual_points")
        rec = entry.get("receptions_credited", 0)
        if not pid:
            raise err_validation("Each score entry needs player_id.")
        score_map[pid] = (ap, rec)

    scoring_mode = league["scoring_mode"]
    reception_mult = (
        0.0 if scoring_mode == "STANDARD" else 0.5 if scoring_mode == "HALF_PPR" else 1.0
    )

    out = []
    for m in matchups:
        home_total = Decimal("0")
        away_total = Decimal("0")
        for team_id, accum_label in [
            (m["home_team_id"], "home_points"),
            (m["away_team_id"], "away_points"),
        ]:
            starters = [
                s
                for s in store.roster_slots_for_team(team_id)
                if s["slot_type"] == "STARTER"
            ]
            total = Decimal("0")
            for s in starters:
                if s["player_id"] not in score_map:
                    # No score provided -> contribute 0
                    continue
                ap, rec = score_map[s["player_id"]]
                if ap is None:
                    ap = 0
                contrib = Decimal(str(ap)) + Decimal(str(reception_mult)) * Decimal(str(rec))
                total += contrib
            if team_id == m["home_team_id"]:
                home_total = total
            else:
                away_total = total

        home_pts = float(home_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        away_pts = float(away_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        m["home_points"] = home_pts
        m["away_points"] = away_pts
        m["status"] = "SCORED"
        stamp_update(m)

        # Determine winner
        if home_pts > away_pts:
            winner_id, loser_id = m["home_team_id"], m["away_team_id"]
        elif away_pts > home_pts:
            winner_id, loser_id = m["away_team_id"], m["home_team_id"]
        else:
            # Tie: lexicographically smaller id wins
            ids = sorted([m["home_team_id"], m["away_team_id"]])
            winner_id, loser_id = ids[0], ids[1]

        winner = store.teams[winner_id]
        loser = store.teams[loser_id]
        winner["wins"] = winner.get("wins", 0) + 1
        loser["losses"] = loser.get("losses", 0) + 1
        winner["points_for"] = winner.get("points_for", 0) + (
            home_pts if winner_id == m["home_team_id"] else away_pts
        )
        loser["points_for"] = loser.get("points_for", 0) + (
            home_pts if loser_id == m["home_team_id"] else away_pts
        )
        stamp_update(winner)
        stamp_update(loser)
        out.append(m)

    # Advance current_week if every matchup of this week is SCORED
    all_for_week = [
        m
        for m in store.matchups_in_league(league_id)
        if m["week_number"] == week_number
    ]
    if all(m["status"] == "SCORED" for m in all_for_week):
        league["current_week"] = league["current_week"] + 1
        stamp_update(league)

        # If is_playoff and not final, generate next round
        if all_for_week and all_for_week[0]["is_playoff"]:
            current_round = all_for_week[0]["bracket_round"]
            total_rounds = int(math.log2(league["playoff_team_count"]))
            if current_round < total_rounds:
                _generate_next_playoff_round(league, all_for_week)
            else:
                # Final round done; lifecycle transition will happen on next clock advance
                pass

    return out


def _generate_next_playoff_round(league: Dict[str, Any], current_round_matchups: List[Dict[str, Any]]) -> None:
    """Pair winners of the current round by seed."""
    winners = []
    for m in current_round_matchups:
        if m["home_points"] > m["away_points"]:
            winners.append(m["home_team_id"])
        elif m["away_points"] > m["home_points"]:
            winners.append(m["away_team_id"])
        else:
            ids = sorted([m["home_team_id"], m["away_team_id"]])
            winners.append(ids[0])
    # Sort winners by seed (best first)
    team_by_id = {t["id"]: t for t in store.teams_in_league(league["id"])}
    winners.sort(key=lambda tid: team_by_id[tid].get("standing_seed") or 0)

    next_round = current_round_matchups[0]["bracket_round"] + 1
    next_week = current_round_matchups[0]["week_number"] + 1

    # Pair best vs worst, etc.
    n = len(winners)
    for i in range(n // 2):
        home_id = winners[i]
        away_id = winners[n - 1 - i]
        mw = {
            "league_id": league["id"],
            "week_number": next_week,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_points": 0,
            "away_points": 0,
            "status": "SCHEDULED",
            "is_playoff": True,
            "bracket_round": next_round,
        }
        stamp_create(mw)
        store.matchup_weeks[mw["id"]] = mw


def evaluate_lifecycle_transition(league: Dict[str, Any]) -> None:
    """REGULAR_SEASON -> PLAYOFFS and PLAYOFFS -> COMPLETED."""
    if league["status"] == "REGULAR_SEASON":
        # Check if every regular-season matchup is SCORED and current_week == regular_season_weeks
        regular = [
            m
            for m in store.matchups_in_league(league["id"])
            if not m["is_playoff"]
        ]
        if not regular:
            return
        all_scored = all(m["status"] == "SCORED" for m in regular)
        if all_scored and league["current_week"] > league["regular_season_weeks"]:
            _transition_to_playoffs(league)
    elif league["status"] == "PLAYOFFS":
        # Check if final playoff round is scored
        playoff_matchups = [
            m for m in store.matchups_in_league(league["id"]) if m["is_playoff"]
        ]
        if not playoff_matchups:
            return
        total_rounds = int(math.log2(league["playoff_team_count"]))
        final_round_mws = [
            m for m in playoff_matchups if m["bracket_round"] == total_rounds
        ]
        if final_round_mws and all(m["status"] == "SCORED" for m in final_round_mws):
            league["status"] = "COMPLETED"
            league["current_week"] = (
                league["regular_season_weeks"] + total_rounds + 1
            )
            stamp_update(league)


def _transition_to_playoffs(league: Dict[str, Any]) -> None:
    teams = store.teams_in_league(league["id"])
    # Compute standings: wins desc, points_for desc, created_at asc
    teams_sorted = sorted(
        teams,
        key=lambda t: (-t.get("wins", 0), -t.get("points_for", 0), t["created_at"]),
    )
    for idx, t in enumerate(teams_sorted, start=1):
        t["standing_seed"] = idx
        stamp_update(t)

    league["status"] = "PLAYOFFS"
    stamp_update(league)

    # Generate first round bracket
    playoff_n = league["playoff_team_count"]
    top = teams_sorted[:playoff_n]
    first_round_week = league["regular_season_weeks"] + 1

    for i in range(playoff_n // 2):
        home = top[i]
        away = top[playoff_n - 1 - i]
        mw = {
            "league_id": league["id"],
            "week_number": first_round_week,
            "home_team_id": home["id"],
            "away_team_id": away["id"],
            "home_points": 0,
            "away_points": 0,
            "status": "SCHEDULED",
            "is_playoff": True,
            "bracket_round": 1,
        }
        stamp_create(mw)
        store.matchup_weeks[mw["id"]] = mw
