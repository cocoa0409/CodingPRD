"""Offer-time eligibility gauntlet (PRD §3.4, validations §1.4 priorities 6-12).

Checks run in this exact order (PRD §3.4):
  1. Suspension      -> ERR_OFFICIAL_SUSPENDED   (409)
  2. Rank            -> ERR_RANK_INELIGIBLE       (422)
  3. Conflict        -> ERR_CONFLICT_OF_INTEREST  (422)
  4. Availability    -> ERR_OUTSIDE_AVAILABILITY  (422)
  5. Double-booking  -> ERR_OFFICIAL_DOUBLE_BOOKED(409)
  6. Travel radius   -> ERR_OUTSIDE_TRAVEL_RADIUS (422)
  7. Postseason gate -> ERR_NOT_POSTSEASON_ELIGIBLE (422)
"""
import db
from errors import (
    err, ERR_OFFICIAL_SUSPENDED, ERR_RANK_INELIGIBLE,
    ERR_CONFLICT_OF_INTEREST, ERR_OUTSIDE_AVAILABILITY,
    ERR_OFFICIAL_DOUBLE_BOOKED, ERR_OUTSIDE_TRAVEL_RADIUS,
    ERR_NOT_POSTSEASON_ELIGIBLE,
)
from services import calc, intervals, derive
from timeutil import parse_iso

REFEREE_RANKS = {"SENIOR", "MASTER"}


def _conflicts_for(official_id):
    return [c for c in db.conflict_declarations.values()
            if c["official_id"] == official_id]


def _filled_official_ids_on_game(game_id):
    """official_ids holding a FILLED slot on this game (via live ACCEPTED
    assignments referenced by the slot's current_assignment_id)."""
    ids = set()
    for s in db.crew_slots.values():
        if s["game_id"] != game_id or s["status"] != "FILLED":
            continue
        aid = s.get("current_assignment_id")
        a = db.assignments.get(aid) if aid else None
        if a is not None:
            ids.add(a["official_id"])
    return ids


def check_suspension(official):
    if official["status"] != "ACTIVE":
        err(ERR_OFFICIAL_SUSPENDED, "official is not ACTIVE")


def check_rank(slot, official):
    if slot["position"] == "REFEREE" and official["rank"] not in REFEREE_RANKS:
        err(ERR_RANK_INELIGIBLE, "REFEREE slot requires SENIOR or MASTER rank")


def check_conflict(official, game):
    conflicts = _conflicts_for(official["id"])
    # TEAM-scoped conflict naming this game's home_team or away_team.
    for c in conflicts:
        if c["scope"] == "TEAM" and c.get("team_name") in (
                game["home_team"], game["away_team"]):
            err(ERR_CONFLICT_OF_INTEREST, "team conflict with this game")
    # OFFICIAL-scoped conflict with any official already FILLED on this game.
    filled_ids = _filled_official_ids_on_game(game["id"])
    for c in conflicts:
        if c["scope"] == "OFFICIAL" and c.get("peer_official_id") in filled_ids:
            err(ERR_CONFLICT_OF_INTEREST, "peer-official conflict on this game")


def check_availability(official, game):
    g_start, g_end = intervals.game_interval(game)
    windows = [w for w in db.availabilities.values()
               if w["official_id"] == official["id"] and w["status"] == "ACTIVE"]
    # Must not intersect any ACTIVE BLACKOUT window.
    for w in windows:
        if w["kind"] != "BLACKOUT":
            continue
        bs = parse_iso(w["window_start_utc"])
        be = parse_iso(w["window_end_utc"])
        if intervals.overlaps(g_start, g_end, bs, be):
            err(ERR_OUTSIDE_AVAILABILITY, "game intersects a BLACKOUT window")
    # Must lie entirely inside at least one ACTIVE AVAILABLE window.
    covered = False
    for w in windows:
        if w["kind"] != "AVAILABLE":
            continue
        ws = parse_iso(w["window_start_utc"])
        we = parse_iso(w["window_end_utc"])
        if intervals.contains(ws, we, g_start, g_end):
            covered = True
            break
    if not covered:
        err(ERR_OUTSIDE_AVAILABILITY, "game not covered by an AVAILABLE window")


def check_double_booking(official, game, statuses=("OFFERED", "ACCEPTED")):
    """The game interval must not overlap any OTHER game's interval where this
    official already holds an assignment in one of `statuses`."""
    g_start, g_end = intervals.game_interval(game)
    for a in db.assignments.values():
        if a["official_id"] != official["id"]:
            continue
        if a["status"] not in statuses:
            continue
        if a["game_id"] == game["id"]:
            continue
        other = db.games.get(a["game_id"])
        if other is None:
            continue
        os, oe = intervals.game_interval(other)
        if intervals.overlaps(g_start, g_end, os, oe):
            err(ERR_OFFICIAL_DOUBLE_BOOKED,
                "official already booked on an overlapping game")


def check_travel(official, game, distance_miles):
    if distance_miles > float(official["max_travel_miles"]):
        err(ERR_OUTSIDE_TRAVEL_RADIUS, "venue beyond official's travel radius")


def check_postseason(official, game):
    if not game.get("is_postseason"):
        return
    breakdown = derive.compute_eligibility_breakdown(official)
    if not breakdown["postseason_eligible"]:
        err(ERR_NOT_POSTSEASON_ELIGIBLE, "official is not postseason eligible")


def run_offer_gauntlet(official, slot, game):
    """Run checks 1-7 in order. Returns the frozen distance_miles."""
    check_suspension(official)
    check_rank(slot, official)
    check_conflict(official, game)
    check_availability(official, game)
    check_double_booking(official, game, statuses=("OFFERED", "ACCEPTED"))
    distance_miles = calc.great_circle_miles(
        official["home_lat"], official["home_lon"],
        game["venue_lat"], game["venue_lon"])
    check_travel(official, game, distance_miles)
    check_postseason(official, game)
    return distance_miles
