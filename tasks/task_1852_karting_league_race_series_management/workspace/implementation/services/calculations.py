"""Calculation rules (scaffold 1.3): session_points, season_standings with
championship_tiebreak, practice_billing helpers, and session re-ranking used
by the incident penalty cascade.

All point figures are integers with no rounding (PRD 2.5).
"""
from functools import cmp_to_key

from db import db
from services.core import (
    FASTEST_LAP_MAX_POSITION,
    COUNTED_EVENT_STATES,
    entry_event_points,
    touch,
)


def _season_of_session(session):
    event = db["events"].get(session["event_id"])
    if event is None:
        return None
    return db["seasons"].get(event["season_id"])


def session_results(session_id):
    return [r for r in db["results"].values() if r["session_id"] == session_id]


def recompute_session_points(session, rerank=False):
    """session_points: rewrite finish_position (only when rerank=True, per the
    incident cascade's effective-time ordering), is_fastest_lap and
    points_awarded for every result of the session, in a single pass.

    rerank ordering: effective_total_ms = total_time_ms + penalty_seconds_applied*1000
    ascending; ties broken by the result's pre-rank finish_position ascending.
    """
    results = session_results(session["id"])
    if not results:
        return
    season = _season_of_session(session)
    scheme = season["points_scheme"] if season else []
    bonus_points = season["fastest_lap_bonus_points"] if season else 0

    # hop 2 of the penalty cascade: re-rank and rewrite finish_position
    new_pos = {}
    if rerank:
        ordered = sorted(
            results,
            key=lambda r: (
                r["total_time_ms"] + r["penalty_seconds_applied"] * 1000,
                r["finish_position"],
            ),
        )
        for idx, r in enumerate(ordered, start=1):
            new_pos[r["id"]] = idx
    else:
        for r in results:
            new_pos[r["id"]] = r["finish_position"]

    # fastest lap: min best_lap_ms; tie -> lower finish_position (post-rerank)
    fastest = min(
        results,
        key=lambda r: (r["best_lap_ms"], new_pos[r["id"]]),
    )

    scoring_session = session["session_type"] in ("HEAT", "MAIN")
    for r in results:
        pos = new_pos[r["id"]]
        is_fast = r["id"] == fastest["id"]
        if scoring_session:
            base = scheme[pos - 1] if 1 <= pos <= len(scheme) else 0
            bonus = bonus_points if (is_fast and pos <= FASTEST_LAP_MAX_POSITION) else 0
            pts = base + bonus
        else:
            pts = 0
        entry = db["entries"].get(r["entry_id"])
        if entry is not None and entry["status"] == "DISQUALIFIED":
            pts = 0

        changed = False
        if r["finish_position"] != pos:
            r["finish_position"] = pos
            # position change moves PROVISIONAL -> AMENDED; AMENDED stays AMENDED
            if r["status"] == "PROVISIONAL":
                r["status"] = "AMENDED"
            changed = True
        if r["is_fastest_lap"] != is_fast:
            r["is_fastest_lap"] = is_fast
            changed = True
        if r["points_awarded"] != pts:
            r["points_awarded"] = pts
            changed = True
        if changed:
            touch(r)


# --- season standings (calculations.season_standings + championship_tiebreak) --

def compute_standings(season, race_class):
    """Returns the ordered list of standings rows for one class of a season.

    Counted events: child RaceEvents in COMPLETED or FINALIZED (CANCELLED
    excluded). Per driver: provisional_points sums every counted event;
    final_points drops the drop_rounds lowest per-event scores (score ASC,
    round_number ASC at the drop boundary).
    """
    counted = {}
    for e in db["events"].values():
        if e["season_id"] == season["id"] and e["status"] in COUNTED_EVENT_STATES:
            counted[e["id"]] = e

    per_driver = {}
    for en in db["entries"].values():
        if en["class_id"] != race_class["id"]:
            continue
        ev = counted.get(en["event_id"])
        if ev is None:
            continue
        per_driver.setdefault(en["driver_id"], []).append(
            (ev["round_number"], entry_event_points(en), en)
        )

    rows = []
    for driver_id, items in per_driver.items():
        provisional = sum(p for _, p, _ in items)
        ordered = sorted(items, key=lambda t: (t[1], t[0]))  # score ASC, round ASC
        k = season["drop_rounds"]
        if k >= len(ordered):
            dropped, kept = ordered, []
        else:
            dropped, kept = ordered[:k], ordered[k:]
        final = sum(p for _, p, _ in kept)
        dropped_round_numbers = [rnd for rnd, _, _ in dropped]

        # championship tiebreak inputs: MAIN-session finish positions over the
        # driver's counted, non-dropped events only
        main_positions = []  # list of (finish_position, round_number)
        for round_no, _, en in kept:
            for r in db["results"].values():
                if r["entry_id"] != en["id"]:
                    continue
                sess = db["sessions"].get(r["session_id"])
                if sess is not None and sess["session_type"] == "MAIN":
                    main_positions.append((r["finish_position"], round_no))

        driver = db["drivers"].get(driver_id)
        rows.append({
            "driver_id": driver_id,
            "class_id": race_class["id"],
            "provisional_points": provisional,
            "final_points": final,
            "dropped_round_numbers": dropped_round_numbers,
            "_main_positions": main_positions,
            "_driver_created_at": driver["created_at"] if driver else "",
        })

    if season["status"] in ("FINALIZED", "AWARDS_CONCLUDED"):
        rows.sort(key=cmp_to_key(_final_rank_cmp))
    else:
        rows.sort(key=lambda r: (-r["provisional_points"], r["_driver_created_at"]))

    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
        del row["_main_positions"]
        del row["_driver_created_at"]
    return rows


def _countback_counts(main_positions):
    counts = {}
    for pos, _ in main_positions:
        counts[pos] = counts.get(pos, 0) + 1
    return counts


def _latest_best_round(main_positions):
    """The highest round_number at which the driver achieved their best counted
    MAIN finish; -1 when the driver has no counted MAIN results."""
    if not main_positions:
        return -1
    best = min(pos for pos, _ in main_positions)
    return max(rnd for pos, rnd in main_positions if pos == best)


def _final_rank_cmp(a, b):
    # 1. final_points DESC
    if a["final_points"] != b["final_points"]:
        return -1 if a["final_points"] > b["final_points"] else 1
    # 2. countback: 1st-place MAIN finishes DESC, then 2nd, then 3rd, ...
    ca, cb = _countback_counts(a["_main_positions"]), _countback_counts(b["_main_positions"])
    max_pos = max(list(ca.keys()) + list(cb.keys()) + [0])
    for p in range(1, max_pos + 1):
        xa, xb = ca.get(p, 0), cb.get(p, 0)
        if xa != xb:
            return -1 if xa > xb else 1
    # 3. latest best round DESC (more recent best result wins)
    la, lb = _latest_best_round(a["_main_positions"]), _latest_best_round(b["_main_positions"])
    if la != lb:
        return -1 if la > lb else 1
    # 4. earlier-registered driver wins
    if a["_driver_created_at"] != b["_driver_created_at"]:
        return -1 if a["_driver_created_at"] < b["_driver_created_at"] else 1
    return 0
