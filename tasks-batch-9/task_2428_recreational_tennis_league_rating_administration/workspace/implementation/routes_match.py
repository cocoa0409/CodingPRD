"""Matches: fixtures, the slot geometry, confirmation, mark-played and defaults."""

from datetime import timedelta

from flask import Blueprint, request

import credit
import derive
from auth import authenticate
from errors import ApiError
from response import object_response, paginate
from routes_common import (ALL_ROLES, CAPTAIN_ONLY, COORDINATOR_ONLY, apply_filters, found,
                           reference)
from store import db, insert, iso, new_id, now, now_iso, parse_instant, public, sorted_rows, touch
from validation import (as_int, bad, body, opt_enum, opt_string, present, reject_unknown,
                        req_enum, req_instant, req_int, req_string)

import routes_scorecard as scorecard

bp = Blueprint("match", __name__, url_prefix="/tennis")
bp.register_blueprint(scorecard.bp)

PLAYABLE_LEAGUE_STATUSES = ("ROSTERS_LOCKED", "IN_PLAY", "PLAYOFFS")
STAGES = ("REGULAR", "PLAYOFF")
DEFAULT_SIDES = ("HOME", "AWAY", "BOTH")
DEFAULT_KINDS = ("NO_SHOW", "SHORT_ROSTER")
FROZEN_TEAM_STATUSES = ("WITHDRAWN", "DISQUALIFIED")


@bp.post("/matches")
def create_match():
    authenticate(COORDINATOR_ONLY)
    payload = body()

    league = _payload_ref(payload, "league_id", "leagues")
    home = _payload_ref(payload, "home_team_id", "teams")
    away = _payload_ref(payload, "away_team_id", "teams")

    reject_unknown(payload, {"league_id", "home_team_id", "away_team_id", "stage", "round_number"})
    req_string(payload, "league_id", 1)
    req_string(payload, "home_team_id", 1)
    req_string(payload, "away_team_id", 1)
    stage = opt_enum(payload, "stage", STAGES, "REGULAR")
    round_number = req_int(payload, "round_number", 1)
    if league is None or home is None or away is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    if league.get("status") not in PLAYABLE_LEAGUE_STATUSES:
        raise ApiError("ERR_LEAGUE_NOT_IN_PLAY")
    for team in (home, away):
        if team.get("status") in FROZEN_TEAM_STATUSES:
            raise ApiError("ERR_TEAM_STATE_INVALID")
    if home["id"] == away["id"]:
        raise ApiError("ERR_TEAM_LEAGUE_MISMATCH")
    for team in (home, away):
        if team.get("league_id") != league["id"]:
            raise ApiError("ERR_TEAM_LEAGUE_MISMATCH")

    record = {
        "id": new_id(),
        "league_id": league["id"],
        "home_team_id": home["id"],
        "away_team_id": away["id"],
        "stage": stage,
        "round_number": round_number,
        "facility_id": None,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "courts_required": None,
        "schedule_status": "UNSCHEDULED",
        "result_status": "PENDING",
        "winner_team_id": None,
        "home_lines_won": 0,
        "away_lines_won": 0,
        "home_sets_won": 0,
        "away_sets_won": 0,
        "home_games_won": 0,
        "away_games_won": 0,
        "line_results": [],
        "default_side": None,
        "default_kind": None,
        "verified_at": None,
    }
    insert("matches", record)
    return object_response(public(record), 201)


def _payload_ref(payload, field, collection):
    raw = payload.get(field)
    if isinstance(raw, str) and raw.strip():
        return reference(collection, raw.strip())
    return None


@bp.get("/matches/<match_id>")
def get_match(match_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("matches", match_id)))


@bp.get("/matches")
def list_matches():
    authenticate(ALL_ROLES)
    spec = {"league_id": ("league_id", "str"), "home_team_id": ("home_team_id", "str"),
            "away_team_id": ("away_team_id", "str"), "facility_id": ("facility_id", "str"),
            "winner_team_id": ("winner_team_id", "str"), "stage": ("stage", "str"),
            "round_number": ("round_number", "int"),
            "schedule_status": ("schedule_status", "str"),
            "result_status": ("result_status", "str")}
    rows = apply_filters(list(db.matches.values()), spec)
    start_from = request.args.get("scheduled_from")
    start_to = request.args.get("scheduled_to")
    if start_from:
        bound = parse_instant(start_from)
        rows = [r for r in rows if r.get("scheduled_start_at")
                and parse_instant(r["scheduled_start_at"]) >= bound] if bound else []
    if start_to:
        bound = parse_instant(start_to)
        rows = [r for r in rows if r.get("scheduled_start_at")
                and parse_instant(r["scheduled_start_at"]) <= bound] if bound else []
    return paginate(sorted_rows(rows), public)


@bp.post("/matches/<match_id>/schedule")
def schedule_match(match_id):
    authenticate(COORDINATOR_ONLY)
    match = found("matches", match_id)
    payload = body()
    facility = _payload_ref(payload, "facility_id", "facilities")

    reject_unknown(payload, {"facility_id", "scheduled_start_at", "courts_required",
                             "expected_match_version"})
    req_string(payload, "facility_id", 1)
    start_at = req_instant(payload, "scheduled_start_at")
    league = db.leagues.get(match.get("league_id")) or {}
    courts_required = req_int(payload, "courts_required", 1, int(league.get("lines_per_match") or 3))
    if present(payload, "expected_match_version"):
        as_int(payload["expected_match_version"], "expected_match_version")
    if facility is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    if not present(payload, "expected_match_version"):
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(payload["expected_match_version"]) != int(match.get("version")):
        raise ApiError("ERR_STALE_MATCH_VERSION")

    if league.get("status") not in PLAYABLE_LEAGUE_STATUSES:
        raise ApiError("ERR_LEAGUE_NOT_IN_PLAY")
    if match.get("schedule_status") not in ("UNSCHEDULED", "SCHEDULED"):
        raise ApiError("ERR_MATCH_SCHEDULE_STATE_INVALID")
    if facility.get("section_id") != league.get("section_id"):
        raise ApiError("ERR_FACILITY_SECTION_MISMATCH")

    season_end = parse_instant(league.get("season_end_at"))
    if not start_at > now():
        raise ApiError("ERR_MATCH_START_OUTSIDE_WINDOW")
    if match.get("stage") == "REGULAR":
        if start_at > season_end:
            raise ApiError("ERR_MATCH_START_OUTSIDE_WINDOW")
    elif not start_at > season_end:
        raise ApiError("ERR_MATCH_START_OUTSIDE_WINDOW")

    occupancy_minutes = (int(league.get("match_duration_minutes") or 0)
                         + int(facility.get("turnaround_buffer_minutes") or 0))
    end_occupancy = start_at + timedelta(minutes=occupancy_minutes)
    if not credit.facility_capacity_available(facility, league, match["id"], start_at,
                                              end_occupancy, courts_required):
        raise ApiError("ERR_FACILITY_COURTS_EXCEEDED")
    for side in ("home_team_id", "away_team_id"):
        if credit.team_has_conflict(match.get(side), league, match["id"], start_at):
            raise ApiError("ERR_TEAM_DATE_CONFLICT")

    match["facility_id"] = facility["id"]
    match["scheduled_start_at"] = iso(start_at)
    match["scheduled_end_at"] = iso(start_at + timedelta(
        minutes=int(league.get("match_duration_minutes") or 0)))
    match["courts_required"] = courts_required
    match["schedule_status"] = "SCHEDULED"
    touch(match)
    return object_response(public(match))


@bp.post("/matches/<match_id>/confirm")
def confirm_match(match_id):
    actor = authenticate(CAPTAIN_ONLY)
    match = found("matches", match_id)
    home = db.teams.get(match.get("home_team_id"))
    if home is None or home.get("captain_player_id") != actor.user_id:
        raise ApiError("ERR_NOT_TEAM_CAPTAIN")
    reject_unknown(body(), set())

    league = db.leagues.get(match.get("league_id")) or {}
    if league.get("status") not in ("IN_PLAY", "PLAYOFFS"):
        raise ApiError("ERR_LEAGUE_NOT_IN_PLAY")
    if match.get("schedule_status") != "SCHEDULED":
        raise ApiError("ERR_MATCH_SCHEDULE_STATE_INVALID")
    away = db.teams.get(match.get("away_team_id"))
    for team in (home, away):
        if team is None or team.get("status") != "IN_PLAY":
            raise ApiError("ERR_TEAM_STATE_INVALID")
    for team in (home, away):
        if not team.get("roster_compliant"):
            raise ApiError("ERR_TEAM_ROSTER_NONCOMPLIANT")
    if not now() < parse_instant(match.get("scheduled_start_at")):
        raise ApiError("ERR_MATCH_START_OUTSIDE_WINDOW")

    match["schedule_status"] = "CONFIRMED"
    touch(match)
    return object_response(public(match))


@bp.post("/matches/<match_id>/mark-played")
def mark_played(match_id):
    authenticate(COORDINATOR_ONLY)
    match = found("matches", match_id)
    reject_unknown(body(), set())

    league = db.leagues.get(match.get("league_id")) or {}
    if league.get("status") not in PLAYABLE_LEAGUE_STATUSES:
        raise ApiError("ERR_LEAGUE_NOT_IN_PLAY")
    if match.get("schedule_status") != "CONFIRMED":
        raise ApiError("ERR_MATCH_SCHEDULE_STATE_INVALID")
    if now() < parse_instant(match.get("scheduled_end_at")):
        raise ApiError("ERR_MATCH_NOT_YET_PLAYABLE")

    match["schedule_status"] = "PLAYED"
    touch(match)
    return object_response(public(match))


@bp.post("/matches/<match_id>/default")
def record_default(match_id):
    authenticate(COORDINATOR_ONLY)
    match = found("matches", match_id)
    payload = body()
    reject_unknown(payload, {"defaulting_side", "default_kind", "note"})
    side = req_enum(payload, "defaulting_side", DEFAULT_SIDES)
    kind = req_enum(payload, "default_kind", DEFAULT_KINDS)
    opt_string(payload, "note", None, 1)

    if match.get("schedule_status") not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_MATCH_SCHEDULE_STATE_INVALID")
    if match.get("result_status") != "PENDING":
        raise ApiError("ERR_MATCH_RESULT_STATE_INVALID")
    if now() < parse_instant(match.get("scheduled_start_at")):
        raise ApiError("ERR_MATCH_NOT_YET_PLAYABLE")

    league = db.leagues.get(match.get("league_id")) or {}
    totals = credit.resolve_credit(league, match.get("home_team_id"), match.get("away_team_id"),
                                   [], side, kind)
    match.update(totals)
    match["schedule_status"] = "DEFAULTED"
    match["result_status"] = "VERIFIED"
    match["verified_at"] = now_iso()
    touch(match)

    for team_key, defaulting in (("home_team_id", side in ("HOME", "BOTH")),
                                 ("away_team_id", side in ("AWAY", "BOTH"))):
        if not defaulting:
            continue
        team = db.teams.get(match.get(team_key))
        captain = db.players.get((team or {}).get("captain_player_id"))
        if captain is not None:
            derive.issue_strike(captain, "NO_SHOW_DEFAULT",
                                "Team default recorded on match %s" % match["id"], match["id"])

    derive.cascade_result_change(match)
    return object_response(public(match))
