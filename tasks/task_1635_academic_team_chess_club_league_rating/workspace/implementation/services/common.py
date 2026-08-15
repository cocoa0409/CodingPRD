"""Shared domain helpers: serializers, lookups, derived fields."""
from db import store, now_iso
from errors import not_found

OCCUPYING_MEET_STATES = ("SCHEDULED", "PAIRINGS_PUBLISHED", "IN_PROGRESS")


def get_or_404(table, rid, what="resource"):
    obj = table.get(rid)
    if obj is None:
        raise not_found(what)
    return obj


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] += 1


def player_season(player):
    club = store.clubs[player["club_id"]]
    return store.seasons[club["season_id"]]


def club_balance(club_id):
    return sum(le["amount_cents"] for le in store.ledger_entries.values()
               if le["club_id"] == club_id)


MEET_CAP = 10


def club_meet_count(club_id, statuses):
    club = store.clubs[club_id]
    sid = club["season_id"]
    n = 0
    for m in store.meets.values():
        if m["season_id"] != sid:
            continue
        if m["host_club_id"] != club_id and m["away_club_id"] != club_id:
            continue
        if m["status"] in statuses:
            n += 1
    return n


def projected_stipend(club):
    season = store.seasons[club["season_id"]]
    n = club_meet_count(club["id"], OCCUPYING_MEET_STATES + ("COMPLETED",))
    return club["travel_tier"] * season["travel_base_cents"] * min(n, MEET_CAP)


def actual_stipend_meets(club):
    return min(club_meet_count(club["id"], ("COMPLETED",)), MEET_CAP)


def section_current_entries(section_id):
    return sum(1 for e in store.entries.values()
               if e["section_id"] == section_id and e["status"] in ("REGISTERED", "CHECKED_IN", "FINISHED"))


def performance_points(player):
    """Full recompute from sources (PRD 3.5)."""
    pid = player["id"]
    pts = 0
    for p in store.pairings.values():
        if p["status"] != "CONFIRMED":
            continue
        if p["white_player_id"] != pid and p["black_player_id"] != pid:
            continue
        meet = store.meets[p["meet_id"]]
        if meet["status"] not in ("IN_PROGRESS", "COMPLETED"):
            continue
        r = p["result"]
        is_white = (p["white_player_id"] == pid)
        if r == "WHITE_WIN":
            pts += 3 if is_white else 0
        elif r == "BLACK_WIN":
            pts += 0 if is_white else 3
        elif r == "DRAW":
            pts += 1
        elif r == "WHITE_FORFEIT_WIN":
            pts += 1 if is_white else 0
        elif r == "BLACK_FORFEIT_WIN":
            pts += 0 if is_white else 1
        # DOUBLE_FORFEIT: 0
    pts += 2 * sum(1 for e in store.entries.values()
                   if e["player_id"] == pid and e["status"] in ("CHECKED_IN", "FINISHED"))
    return pts


def membership_for(player_id, season_id):
    for m in store.memberships.values():
        if m["player_id"] == player_id and m["season_id"] == season_id:
            return m
    return None
