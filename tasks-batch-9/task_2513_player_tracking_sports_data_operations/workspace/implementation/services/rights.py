"""Rights-window exclusivity and the game minute ledger (PRD §3.7)."""

from datetime import timedelta

import db
from calc import BROADCAST_BUFFER_SECONDS
from util import parse_dt


def recompute_game_ledger(game):
    """Steps 3 of the ledger: two disjoint pools, revoked windows contribute nothing."""
    windows = [w for w in db.rights_windows_of_game(game["id"])
               if w["status"] == "ACTIVE"]
    reserve_allocated = sum(w["allocated_minutes"] for w in windows
                            if w["rights_class"] == "LEAGUE_ARCHIVE")
    net_allocated = sum(w["allocated_minutes"] for w in windows
                        if w["rights_class"] != "LEAGUE_ARCHIVE")
    game["league_reserve_allocated_minutes"] = reserve_allocated
    game["allocated_minutes_total"] = net_allocated
    game["remaining_allocatable_minutes"] = (
        game["net_allocatable_minutes"] - net_allocated)


def territories_collide(left, right):
    """GLOBAL collides with every territory including itself; two country codes
    collide only when they are equal (PRD §3.7)."""
    if left == "GLOBAL" or right == "GLOBAL":
        return True
    return left == right


def _expanded(start, end, seconds):
    if seconds:
        delta = timedelta(seconds=seconds)
        return start - delta, end + delta
    return start, end


def has_rights_window_collision(game_id, rights_class, territory, start, end,
                                exclude_id=None):
    """Closed intervals on both ends, so windows that merely touch collide.

    BROADCAST_LIVE windows are expanded by 300 seconds on each side — on both
    the candidate and each existing window — before the intersection is tested.
    """
    buffer_seconds = (BROADCAST_BUFFER_SECONDS
                      if rights_class == "BROADCAST_LIVE" else 0)
    cand_start, cand_end = _expanded(start, end, buffer_seconds)

    for window in db.rights_windows_of_game(game_id):
        if window["status"] != "ACTIVE":
            continue
        if exclude_id is not None and window["id"] == exclude_id:
            continue
        if window["rights_class"] != rights_class:
            continue
        if not territories_collide(territory, window["territory"]):
            continue
        other_start, other_end = _expanded(
            parse_dt(window["window_start_utc"]),
            parse_dt(window["window_end_utc"]),
            buffer_seconds,
        )
        if cand_start <= other_end and other_start <= cand_end:
            return True
    return False
