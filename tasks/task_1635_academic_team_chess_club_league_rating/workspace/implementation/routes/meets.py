from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso, parse_date
from errors import (invalid_request, state_error, conflict_error,
                    integrity_error, forbidden_ownership, stale_version)
from middleware import require_roles, ALL_ROLES, acting_coach
from response import success_object, success_array, paginate
from services.common import get_or_404, touch, membership_for
from services.serializers import meet_json, pairing_json
from validate import Body, get_body

bp = Blueprint("meets", __name__)

READ = ALL_ROLES
OCCUPYING = ("SCHEDULED", "PAIRINGS_PUBLISHED", "IN_PROGRESS")
NONTERMINAL_PAIRING = ("SCHEDULED", "REPORTED", "DISPUTED")


def _date_occupied(club_id, date_str, exclude_meet_id=None):
    for m in store.meets.values():
        if exclude_meet_id and m["id"] == exclude_meet_id:
            continue
        if m["status"] not in OCCUPYING:
            continue
        if m["scheduled_date"] != date_str:
            continue
        if m["host_club_id"] == club_id or m["away_club_id"] == club_id:
            return True
    return False


def _check_date_free(meet, date_str):
    for cid in (meet["host_club_id"], meet["away_club_id"]):
        if _date_occupied(cid, date_str, exclude_meet_id=meet["id"]):
            raise conflict_error("ERR_MEET_DATE_CONFLICT",
                                 "A club already occupies that date")


def _check_clubs_not_suspended(meet):
    for cid in (meet["host_club_id"], meet["away_club_id"]):
        if store.clubs[cid]["status"] == "SUSPENDED":
            raise integrity_error("ERR_CLUB_SUSPENDED", "Club is SUSPENDED")


def _coach_in_meet_clubs(meet):
    coach = acting_coach()
    if coach is None or coach["club_id"] not in (meet["host_club_id"],
                                                 meet["away_club_id"]):
        raise forbidden_ownership()


@bp.route("/api/meets", methods=["POST"])
@require_roles("ClubCoach", "FederationAdmin")
def create_meet():
    data = get_body()
    # body FKs (rung 4)
    for field, table, what in (("season_id", store.seasons, "season"),
                               ("host_club_id", store.clubs, "club"),
                               ("away_club_id", store.clubs, "club")):
        v = data.get(field)
        if isinstance(v, str):
            get_or_404(table, v, what)
    if g.user_role == "ClubCoach":
        host = data.get("host_club_id")
        if not isinstance(host, str):
            raise invalid_request("host_club_id is required")
        coach = acting_coach()
        if coach is None or coach["club_id"] != host:
            raise forbidden_ownership()
    body = Body(data, {"season_id", "host_club_id", "away_club_id",
                       "scheduled_date", "rounds_count", "boards_count"})
    sid = body.req_str("season_id")
    get_or_404(store.seasons, sid, "season")
    host_id = body.req_str("host_club_id")
    away_id = body.req_str("away_club_id")
    get_or_404(store.clubs, host_id, "club")
    get_or_404(store.clubs, away_id, "club")
    sched = body.req_date("scheduled_date")
    rounds = body.req_int("rounds_count")
    if rounds < 1:
        raise invalid_request("rounds_count must be >= 1")
    boards = body.req_int("boards_count")
    if boards < 1:
        raise invalid_request("boards_count must be >= 1")
    for cid in (host_id, away_id):
        if store.clubs[cid]["status"] == "SUSPENDED":
            raise integrity_error("ERR_CLUB_SUSPENDED", "Club is SUSPENDED")
    if host_id == away_id:
        raise conflict_error("ERR_SAME_CLUB_MEET",
                             "host_club_id must differ from away_club_id")
    now = now_iso()
    m = {"id": new_id(), "_seq": next_seq(), "created_at": now,
         "updated_at": now, "version": 1, "season_id": sid,
         "host_club_id": host_id, "away_club_id": away_id,
         "scheduled_date": sched, "rounds_count": rounds,
         "boards_count": boards, "status": "DRAFT"}
    store.meets[m["id"]] = m
    return success_object(meet_json(m), 201)


@bp.route("/api/meets", methods=["GET"])
@require_roles(*READ)
def list_meets():
    items = list(store.meets.values())
    for param, field in (("season_id", "season_id"),
                         ("host_club_id", "host_club_id"),
                         ("away_club_id", "away_club_id"),
                         ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [m for m in items if m[field] == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([meet_json(m) for m in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/meets/<meetId>", methods=["GET"])
@require_roles(*READ)
def get_meet(meetId):
    m = get_or_404(store.meets, meetId, "meet")
    return success_object(meet_json(m), 200)


@bp.route("/api/meets/<meetId>/schedule", methods=["POST"])
@require_roles("FederationAdmin")
def schedule_meet(meetId):
    get_body()
    m = get_or_404(store.meets, meetId, "meet")
    if m["status"] != "DRAFT":
        raise state_error("ERR_MEET_INVALID_STATE", "Meet is not DRAFT")
    _check_clubs_not_suspended(m)
    _check_date_free(m, m["scheduled_date"])
    season = store.seasons[m["season_id"]]
    if season["status"] != "ACTIVE":
        raise state_error("ERR_SEASON_INVALID_STATE", "Season is not ACTIVE")
    m["status"] = "SCHEDULED"
    touch(m)
    return success_object(meet_json(m), 200)


@bp.route("/api/meets/<meetId>/postpone", methods=["POST"])
@require_roles("ClubCoach", "FederationAdmin")
def postpone_meet(meetId):
    get_body()
    m = get_or_404(store.meets, meetId, "meet")
    if g.user_role == "ClubCoach":
        _coach_in_meet_clubs(m)
    if m["status"] != "SCHEDULED":
        raise state_error("ERR_MEET_INVALID_STATE", "Meet is not SCHEDULED")
    m["status"] = "POSTPONED"
    touch(m)
    return success_object(meet_json(m), 200)


@bp.route("/api/meets/<meetId>/reschedule", methods=["POST"])
@require_roles("FederationAdmin")
def reschedule_meet(meetId):
    data = get_body()
    m = get_or_404(store.meets, meetId, "meet")
    if m["status"] != "POSTPONED":
        raise state_error("ERR_MEET_INVALID_STATE", "Meet is not POSTPONED")
    body = Body(data, {"scheduled_date"})
    new_date = body.req_date("scheduled_date")
    _check_clubs_not_suspended(m)
    _check_date_free(m, new_date)
    m["scheduled_date"] = new_date
    m["status"] = "SCHEDULED"
    touch(m)
    return success_object(meet_json(m), 200)


@bp.route("/api/meets/<meetId>/cancel", methods=["POST"])
@require_roles("FederationAdmin")
def cancel_meet(meetId):
    get_body()
    m = get_or_404(store.meets, meetId, "meet")
    if m["status"] not in ("DRAFT", "SCHEDULED", "POSTPONED"):
        raise state_error("ERR_MEET_INVALID_STATE",
                          "Meet cannot be cancelled from %s" % m["status"])
    m["status"] = "CANCELLED"
    touch(m)
    for p in store.pairings.values():
        if p["meet_id"] == m["id"] and p["status"] in ("SCHEDULED", "REPORTED"):
            p["status"] = "CANCELLED"
            touch(p)
    for a in store.proctor_assignments.values():
        if a.get("meet_id") == m["id"] and a["status"] in ("ASSIGNED", "CONFIRMED"):
            a["status"] = "RELEASED"
            touch(a)
    return success_object(meet_json(m), 200)


@bp.route("/api/meets/<meetId>/pairings", methods=["POST"])
@require_roles("ClubCoach", "FederationAdmin")
def create_pairing(meetId):
    data = get_body()
    m = get_or_404(store.meets, meetId, "meet")
    # body FKs (rung 4)
    for field in ("white_player_id", "black_player_id"):
        v = data.get(field)
        if isinstance(v, str):
            get_or_404(store.players, v, "player")
    # ownership (rung 5)
    if g.user_role == "ClubCoach":
        _coach_in_meet_clubs(m)
    # OCC (rung 6) when present
    if "expected_meet_version" in data and data["expected_meet_version"] is not None:
        ev = data["expected_meet_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise invalid_request("expected_meet_version must be an integer")
        if ev != m["version"]:
            raise stale_version()
    # shape (rung 7)
    body = Body(data, {"round_number", "board_number", "white_player_id",
                       "black_player_id", "expected_meet_version"})
    round_number = body.req_int("round_number")
    board_number = body.req_int("board_number")
    white_id = body.req_str("white_player_id")
    black_id = body.req_str("black_player_id")
    body.req_int("expected_meet_version")
    if not (1 <= round_number <= m["rounds_count"]):
        raise invalid_request("round_number out of bounds")
    if not (1 <= board_number <= m["boards_count"]):
        raise invalid_request("board_number out of bounds")
    # state (rung 8)
    if m["status"] not in ("DRAFT", "SCHEDULED"):
        raise state_error("ERR_MEET_INVALID_STATE",
                          "Meet does not accept pairings in %s" % m["status"])
    white = store.players[white_id]
    black = store.players[black_id]
    # business integrity (rung 9)
    _check_clubs_not_suspended(m)
    for p in (white, black):
        if p["status"] == "SUSPENDED":
            raise integrity_error("ERR_PLAYER_SUSPENDED", "Player is SUSPENDED")
    # business referential (rung 10): membership then club/color
    for p in (white, black):
        mem = membership_for(p["id"], m["season_id"])
        if mem is None or mem["status"] not in ("PAID", "WAIVED"):
            raise conflict_error("ERR_MEMBERSHIP_REQUIRED",
                                 "Player lacks a PAID or WAIVED membership")
    if white["club_id"] != m["host_club_id"] or black["club_id"] != m["away_club_id"]:
        raise conflict_error("ERR_PLAYER_CLUB_MISMATCH",
                             "White must be host-club, black must be away-club")
    # supersede any existing non-terminal pairing at the same slot
    for p in store.pairings.values():
        if (p["meet_id"] == m["id"] and p["round_number"] == round_number
                and p["board_number"] == board_number
                and p["status"] in NONTERMINAL_PAIRING):
            p["status"] = "REPLACED"
            touch(p)
    now = now_iso()
    pairing = {"id": new_id(), "_seq": next_seq(), "created_at": now,
               "updated_at": now, "version": 1, "meet_id": m["id"],
               "round_number": round_number, "board_number": board_number,
               "white_player_id": white_id, "black_player_id": black_id,
               "result": "UNREPORTED", "reported_by_coach_id": None,
               "was_confirmed": False, "confirmed_at": None,
               "status": "SCHEDULED"}
    store.pairings[pairing["id"]] = pairing
    touch(m)  # each pairing write advances the meet's version
    return success_object(pairing_json(pairing), 201)


@bp.route("/api/meets/<meetId>/pairings", methods=["GET"])
@require_roles(*READ)
def list_meet_pairings(meetId):
    m = get_or_404(store.meets, meetId, "meet")
    items = [p for p in store.pairings.values() if p["meet_id"] == m["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([pairing_json(p) for p in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/meets/<meetId>/publish-pairings", methods=["POST"])
@require_roles("FederationAdmin")
def publish_pairings(meetId):
    get_body()
    m = get_or_404(store.meets, meetId, "meet")
    if m["status"] != "SCHEDULED":
        raise state_error("ERR_MEET_INVALID_STATE", "Meet is not SCHEDULED")
    covered = {(p["round_number"], p["board_number"])
               for p in store.pairings.values()
               if p["meet_id"] == m["id"] and p["status"] == "SCHEDULED"}
    for r in range(1, m["rounds_count"] + 1):
        for b in range(1, m["boards_count"] + 1):
            if (r, b) not in covered:
                raise conflict_error("ERR_INCOMPLETE_PAIRINGS",
                                     "Grid slot (%d, %d) is not covered" % (r, b))
    m["status"] = "PAIRINGS_PUBLISHED"
    touch(m)
    return success_object(meet_json(m), 200)


@bp.route("/api/meets/<meetId>/start", methods=["POST"])
@require_roles("FederationAdmin")
def start_meet(meetId):
    get_body()
    m = get_or_404(store.meets, meetId, "meet")
    if m["status"] != "PAIRINGS_PUBLISHED":
        raise state_error("ERR_MEET_INVALID_STATE",
                          "Meet is not PAIRINGS_PUBLISHED")
    if not any(a.get("meet_id") == m["id"] and a["status"] == "CONFIRMED"
               for a in store.proctor_assignments.values()):
        raise conflict_error("ERR_NO_CONFIRMED_PROCTOR",
                             "No CONFIRMED proctor assignment for the meet")
    m["status"] = "IN_PROGRESS"
    touch(m)
    return success_object(meet_json(m), 200)


@bp.route("/api/meets/<meetId>/complete", methods=["POST"])
@require_roles("FederationAdmin")
def complete_meet(meetId):
    get_body()
    m = get_or_404(store.meets, meetId, "meet")
    if m["status"] != "IN_PROGRESS":
        raise state_error("ERR_MEET_INVALID_STATE", "Meet is not IN_PROGRESS")
    for p in store.pairings.values():
        if (p["meet_id"] == m["id"]
                and p["status"] not in ("REPLACED", "CANCELLED", "CONFIRMED")):
            raise conflict_error("ERR_UNCONFIRMED_PAIRINGS",
                                 "All live pairings must be CONFIRMED")
    m["status"] = "COMPLETED"
    touch(m)
    for a in store.proctor_assignments.values():
        if a.get("meet_id") == m["id"] and a["status"] == "CONFIRMED":
            a["status"] = "COMPLETED"
            touch(a)
    # projected_travel_stipend_cents is computed live on club reads, so the
    # newly COMPLETED meet is reflected immediately.
    return success_object(meet_json(m), 200)
