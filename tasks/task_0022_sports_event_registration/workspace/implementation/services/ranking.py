"""Ranking calculation per §3.5."""
from functools import cmp_to_key
from typing import Dict, List, Tuple

import db


def _participant_match_set(event_id: str, pid: str) -> List[dict]:
    return [
        m for m in db.matches.values()
        if m["event_id"] == event_id
        and m["status"] == "LOCKED"
        and pid in (m.get("home_participant_id"), m.get("away_participant_id"))
    ]


def _aggregates_for(event_id: str, pid: str, event_type: str) -> Dict:
    points = 0
    goal_diff = 0
    away_goals = 0
    sets_won = 0
    for m in _participant_match_set(event_id, pid):
        if m["home_participant_id"] == pid:
            my_score = m.get("locked_home_score") or 0
            opp_score = m.get("locked_away_score") or 0
            my_sets = m.get("locked_home_sets_won") or 0
        else:
            my_score = m.get("locked_away_score") or 0
            opp_score = m.get("locked_home_score") or 0
            my_sets = m.get("locked_away_sets_won") or 0
            away_goals += my_score
        goal_diff += (my_score - opp_score)
        if event_type == "SINGLE_ELIM":
            if m.get("winner_participant_id") == pid:
                points += 3
        elif event_type == "ROUND_ROBIN":
            if m.get("winner_participant_id") == pid:
                points += 3
            elif m.get("locked_home_score") == m.get("locked_away_score"):
                points += 1
        elif event_type == "SETS_MATCH":
            points += my_sets
        if event_type == "SETS_MATCH":
            sets_won += my_sets
    return {
        "points": points,
        "goal_difference": goal_diff,
        "away_goals": away_goals,
        "sets_won": sets_won,
    }


def _head_to_head_points(event_id: str, pid: str, peer: str, event_type: str) -> int:
    pts = 0
    for m in _participant_match_set(event_id, pid):
        sides = (m["home_participant_id"], m.get("away_participant_id"))
        if peer not in sides:
            continue
        if event_type == "SINGLE_ELIM":
            if m.get("winner_participant_id") == pid:
                pts += 3
        elif event_type == "ROUND_ROBIN":
            if m.get("winner_participant_id") == pid:
                pts += 3
            elif m.get("locked_home_score") == m.get("locked_away_score"):
                pts += 1
        elif event_type == "SETS_MATCH":
            if m["home_participant_id"] == pid:
                pts += m.get("locked_home_sets_won") or 0
            else:
                pts += m.get("locked_away_sets_won") or 0
    return pts


def recompute_rankings(event_id: str, *, finalize: bool = False) -> None:
    """Recompute aggregates + provisional_rank (and final_rank when finalize=True)."""
    event = db.events.get(event_id)
    if not event:
        return
    event_type = event["event_type"]

    # All participants for this event
    eligible = []
    excluded = []
    for p in db.participants.values():
        if p["event_id"] != event_id:
            continue
        if p["status"] in ("WITHDRAWN", "DISQUALIFIED"):
            excluded.append(p)
        else:
            eligible.append(p)

    # Update aggregates on every RankingEntry (eligible + excluded)
    aggregates_by_pid: Dict[str, Dict] = {}
    for p in db.participants.values():
        if p["event_id"] != event_id:
            continue
        agg = _aggregates_for(event_id, p["id"], event_type)
        aggregates_by_pid[p["id"]] = agg
        re_row = _get_or_create_ranking_entry(event_id, p["id"])
        re_row["points"] = agg["points"]
        re_row["goal_difference"] = agg["goal_difference"]
        re_row["away_goals"] = agg["away_goals"]
        re_row["sets_won"] = agg["sets_won"]
        db.stamp_update(re_row)

    # Sort eligible participants per tie-break sequence
    def cmp_pair(a: dict, b: dict) -> int:
        ag = aggregates_by_pid[a["id"]]
        bg = aggregates_by_pid[b["id"]]
        # 1. -points (desc)
        if ag["points"] != bg["points"]:
            return -1 if ag["points"] > bg["points"] else 1
        # 2. -goal_diff (desc)
        if ag["goal_difference"] != bg["goal_difference"]:
            return -1 if ag["goal_difference"] > bg["goal_difference"] else 1
        # 3. -h2h points (desc)  (only between this pair)
        a_h2h = _head_to_head_points(event_id, a["id"], b["id"], event_type)
        b_h2h = _head_to_head_points(event_id, b["id"], a["id"], event_type)
        if a_h2h != b_h2h:
            return -1 if a_h2h > b_h2h else 1
        # 4. -away_goals (desc)
        if ag["away_goals"] != bg["away_goals"]:
            return -1 if ag["away_goals"] > bg["away_goals"] else 1
        # 5. -sets_won (desc)
        if ag["sets_won"] != bg["sets_won"]:
            return -1 if ag["sets_won"] > bg["sets_won"] else 1
        # 6. id ascending
        if a["id"] < b["id"]:
            return -1
        if a["id"] > b["id"]:
            return 1
        return 0

    sorted_eligible = sorted(eligible, key=cmp_to_key(cmp_pair))

    # Assign provisional_rank starting at 1
    for idx, p in enumerate(sorted_eligible, start=1):
        re_row = _get_or_create_ranking_entry(event_id, p["id"])
        re_row["provisional_rank"] = idx
        db.stamp_update(re_row)

    # Excluded participants: provisional_rank null
    for p in excluded:
        re_row = _get_or_create_ranking_entry(event_id, p["id"])
        re_row["provisional_rank"] = None
        db.stamp_update(re_row)

    # On finalize: copy provisional to final
    if finalize:
        for p in db.participants.values():
            if p["event_id"] != event_id:
                continue
            re_row = _get_or_create_ranking_entry(event_id, p["id"])
            re_row["final_rank"] = re_row.get("provisional_rank")
            db.stamp_update(re_row)
            # Also write to participant.final_rank
            p["final_rank"] = re_row.get("provisional_rank")
            db.stamp_update(p)


def _get_or_create_ranking_entry(event_id: str, pid: str) -> dict:
    for re_row in db.ranking_entries.values():
        if re_row["event_id"] == event_id and re_row["participant_id"] == pid:
            return re_row
    row = {
        "event_id": event_id,
        "participant_id": pid,
        "points": 0,
        "goal_difference": 0,
        "away_goals": 0,
        "sets_won": 0,
        "provisional_rank": None,
        "final_rank": None,
    }
    db.stamp_create(row, common_fields=True)
    db.ranking_entries[row["id"]] = row
    return row
