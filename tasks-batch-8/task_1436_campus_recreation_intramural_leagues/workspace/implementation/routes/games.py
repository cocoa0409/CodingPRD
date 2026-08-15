"""Games: scheduling, reschedule cycle, score reports, finalize, forfeits."""

from flask import Blueprint, g, request

import errors as E
from domain import (game_out, get_or_404, check_booking_fit, check_team_time_conflict,
                    apply_final_effects, apply_forfeit_effects, cancel_assignment)
from store import DB
from util import (body_json, req_str, req_int, req_dt, req_present, is_int,
                  envelope_object, list_response, require_role, stamp_new, touch, now)

bp = Blueprint("games", __name__)

SCHEDULABLE_LEAGUE_STATES = ("SCHEDULING", "IN_SEASON", "PLAYOFFS")


def _validate_game_window(body, require_times=True):
    if require_times:
        start_at = req_dt(body, "start_at")
        end_at = req_dt(body, "end_at")
    else:
        start_at = body.get("start_at")
        end_at = body.get("end_at")
        if start_at is not None:
            from util import parse_dt
            start_at = parse_dt(start_at)
        if end_at is not None:
            from util import parse_dt
            end_at = parse_dt(end_at)
    if start_at is None or end_at is None:
        raise E.err_validation("start_at and end_at are required datetimes")
    if end_at <= start_at:
        raise E.err_validation("end_at must be strictly after start_at")
    if start_at.date() != end_at.date():
        raise E.err_validation("start_at and end_at must fall on the same local date")
    return start_at, end_at


def _temporal_gates(facility, start_at, end_at, home_id, away_id, exclude_game_id=None):
    """Priority-9 fixed sub-order: GAME_IN_PAST -> OUTSIDE_HOURS -> CLOSED ->
    DOUBLE_BOOKED -> TEAM_TIME_CONFLICT."""
    if start_at < now():
        raise E.err_game_in_past()
    check_booking_fit(facility, start_at, end_at, exclude_game_id=exclude_game_id)
    check_team_time_conflict(home_id, away_id, start_at, end_at, exclude_game_id=exclude_game_id)


@bp.route("/v1/leagues/<league_id>/games", methods=["POST"])
def create_game(league_id):
    require_role("LeagueCoordinator")
    league = get_or_404(DB.leagues, league_id)
    body = body_json()
    home_team_id = req_str(body, "home_team_id")
    away_team_id = req_str(body, "away_team_id")
    facility_id = req_str(body, "facility_id")
    home = get_or_404(DB.teams, home_team_id)
    away = get_or_404(DB.teams, away_team_id)
    facility = get_or_404(DB.facilities, facility_id)
    if home_team_id == away_team_id:
        raise E.err_validation("home_team_id and away_team_id must differ")
    start_at, end_at = _validate_game_window(body)
    expected = req_present(body, "expected_league_version")
    if not is_int(expected):
        raise E.err_validation("expected_league_version must be an integer")
    if expected != league["version"]:
        raise E.err_stale_version()
    if league["status"] not in SCHEDULABLE_LEAGUE_STATES:
        raise E.err_invalid_state("League status does not allow game scheduling")
    for team in (home, away):
        if team["status"] in ("SUSPENDED", "WITHDRAWN"):
            raise E.err_invalid_state("A SUSPENDED or WITHDRAWN team cannot be scheduled")
    _temporal_gates(facility, start_at, end_at, home_team_id, away_team_id)
    if home["division_name"] is None or home["division_name"] != away["division_name"]:
        raise E.err_teams_not_in_same_division()
    duration = int((end_at - start_at).total_seconds() // 60)
    game = stamp_new({
        "league_id": league_id,
        "division_name": home["division_name"],
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "facility_id": facility_id,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": duration,
        "status": "SCHEDULED",
        "bracket_round": "REGULAR",
        "next_game_id": None,
        "report_home": None,
        "report_away": None,
        "final_home_score": None,
        "final_away_score": None,
        "actual_duration_minutes": None,
        "forfeiting_team_id": None,
        "_division": home["division_name"],
        "_home_seed": None,
        "_away_seed": None,
        "_sf_group": None,
    })
    DB.games[game["id"]] = game
    touch(league)
    return envelope_object(game_out(game), 201)


@bp.route("/v1/games/<game_id>", methods=["GET"])
def get_game(game_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    game = get_or_404(DB.games, game_id)
    return envelope_object(game_out(game))


@bp.route("/v1/games", methods=["GET"])
def list_games():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    league_id = request.args.get("league_id")
    facility_id = request.args.get("facility_id")
    home_team_id = request.args.get("home_team_id")
    away_team_id = request.args.get("away_team_id")
    status = request.args.get("status")
    bracket_round = request.args.get("bracket_round")
    next_game_id = request.args.get("next_game_id")
    forfeiting_team_id = request.args.get("forfeiting_team_id")
    records = [gm for gm in DB.games.values()
               if (league_id is None or gm["league_id"] == league_id)
               and (facility_id is None or gm["facility_id"] == facility_id)
               and (home_team_id is None or gm["home_team_id"] == home_team_id)
               and (away_team_id is None or gm["away_team_id"] == away_team_id)
               and (status is None or gm["status"] == status)
               and (bracket_round is None or gm["bracket_round"] == bracket_round)
               and (next_game_id is None or gm["next_game_id"] == next_game_id)
               and (forfeiting_team_id is None or gm["forfeiting_team_id"] == forfeiting_team_id)]
    return list_response(records, game_out)


@bp.route("/v1/games/<game_id>/reschedule", methods=["POST"])
def reschedule_game(game_id):
    require_role("LeagueCoordinator")
    game = get_or_404(DB.games, game_id)
    body = body_json()
    facility_id = body.get("facility_id")
    if facility_id is not None:
        if not isinstance(facility_id, str) or not facility_id.strip():
            raise E.err_validation("facility_id must be a non-empty string")
        facility = get_or_404(DB.facilities, facility_id)
    else:
        facility = DB.facilities.get(game["facility_id"])
    start_at, end_at = _validate_game_window(body)
    if facility is None:
        raise E.err_validation("facility_id is required for a game with no facility")
    league = DB.leagues.get(game["league_id"])
    if league is None or league["status"] not in SCHEDULABLE_LEAGUE_STATES:
        raise E.err_invalid_state("League status does not allow rescheduling")
    if game["status"] not in ("SCHEDULED", "RESCHEDULE_REQUIRED"):
        raise E.err_invalid_state("Only SCHEDULED or RESCHEDULE_REQUIRED games can be rescheduled")
    _temporal_gates(facility, start_at, end_at, game["home_team_id"], game["away_team_id"],
                    exclude_game_id=game["id"])
    if game["status"] == "SCHEDULED":
        for a in list(DB.assignments.values()):
            if a["game_id"] == game["id"]:
                cancel_assignment(a)
    game["start_at"] = start_at
    game["end_at"] = end_at
    game["facility_id"] = facility["id"]
    game["duration_minutes"] = int((end_at - start_at).total_seconds() // 60)
    game["status"] = "SCHEDULED"
    touch(game)
    return envelope_object(game_out(game))


def _score_fields(body):
    home_score = req_int(body, "home_score")
    away_score = req_int(body, "away_score")
    sportsmanship = req_int(body, "opponent_sportsmanship")
    if home_score < 0 or away_score < 0:
        raise E.err_validation("scores must be >= 0")
    if not (1 <= sportsmanship <= 5):
        raise E.err_validation("opponent_sportsmanship must be in 1..5")
    return home_score, away_score, sportsmanship


@bp.route("/v1/games/<game_id>/score-reports", methods=["POST"])
def submit_score_report(game_id):
    require_role("Member")
    game = get_or_404(DB.games, game_id)
    body = body_json()
    side = body.get("side")
    if not isinstance(side, str) or side not in ("HOME", "AWAY"):
        raise E.err_validation("side must be HOME or AWAY")
    side_team_id = game["home_team_id"] if side == "HOME" else game["away_team_id"]
    side_team = DB.teams.get(side_team_id)
    if side_team is None or side_team["captain_member_id"] != g.user_id:
        raise E.err_forbidden("Only the captain of the reported side may file a score report")
    home_score, away_score, sportsmanship = _score_fields(body)
    if game["status"] not in ("SCHEDULED", "PLAYED_PENDING_CONFIRM"):
        raise E.err_game_not_reportable("Game is not in a reportable status")
    if game["start_at"] is None or now() < game["start_at"]:
        raise E.err_game_not_reportable("Game has not started yet")
    report = {
        "home_score": home_score,
        "away_score": away_score,
        "opponent_sportsmanship": sportsmanship,
        "reported_at": now(),
    }
    if game["status"] == "SCHEDULED":
        if side == "HOME":
            game["report_home"] = report
        else:
            game["report_away"] = report
        game["status"] = "PLAYED_PENDING_CONFIRM"
        touch(game)
        return envelope_object(game_out(game), 201)
    # PLAYED_PENDING_CONFIRM: second report must come from the other side.
    stored_side = "HOME" if game["report_home"] is not None else "AWAY"
    if side == stored_side:
        raise E.err_duplicate_score_report()
    stored = game["report_home"] if stored_side == "HOME" else game["report_away"]
    scores_match = (home_score == stored["home_score"] and away_score == stored["away_score"])
    if scores_match and game["bracket_round"] != "REGULAR" and home_score == away_score:
        raise E.err_tie_not_allowed()
    if side == "HOME":
        game["report_home"] = report
    else:
        game["report_away"] = report
    if scores_match:
        # Matching reports: each team receives the opponent report's rating.
        home_rating = game["report_away"]["opponent_sportsmanship"]
        away_rating = game["report_home"]["opponent_sportsmanship"]
        apply_final_effects(game, home_score, away_score, home_rating, away_rating)
    else:
        game["status"] = "DISPUTED"
        touch(game)
    return envelope_object(game_out(game), 201)


@bp.route("/v1/games/<game_id>/finalize", methods=["POST"])
def finalize_game(game_id):
    require_role("RecAdmin")
    game = get_or_404(DB.games, game_id)
    body = body_json()
    home_score = req_int(body, "home_score")
    away_score = req_int(body, "away_score")
    home_sports = req_int(body, "home_sportsmanship")
    away_sports = req_int(body, "away_sportsmanship")
    actual_duration = req_int(body, "actual_duration_minutes")
    if home_score < 0 or away_score < 0:
        raise E.err_validation("scores must be >= 0")
    if not (1 <= home_sports <= 5) or not (1 <= away_sports <= 5):
        raise E.err_validation("sportsmanship ratings must be in 1..5")
    if actual_duration < 0:
        raise E.err_validation("actual_duration_minutes must be >= 0")
    if game["status"] not in ("PLAYED_PENDING_CONFIRM", "DISPUTED"):
        raise E.err_invalid_state("Only PLAYED_PENDING_CONFIRM or DISPUTED games can be finalized")
    if game["bracket_round"] != "REGULAR" and home_score == away_score:
        raise E.err_tie_not_allowed()
    game["actual_duration_minutes"] = actual_duration
    apply_final_effects(game, home_score, away_score, home_sports, away_sports)
    return envelope_object(game_out(game))


@bp.route("/v1/games/<game_id>/declare-forfeit", methods=["POST"])
def declare_forfeit(game_id):
    require_role("LeagueCoordinator")
    game = get_or_404(DB.games, game_id)
    body = body_json()
    forfeiting_team_id = req_present(body, "forfeiting_team_id")
    if game["status"] not in ("SCHEDULED", "RESCHEDULE_REQUIRED"):
        raise E.err_invalid_state("Only SCHEDULED or RESCHEDULE_REQUIRED games can be forfeited")
    if game["start_at"] is not None and now() < game["start_at"]:
        raise E.err_game_not_reportable("Game has not started yet")
    if forfeiting_team_id not in (game["home_team_id"], game["away_team_id"]):
        raise E.err_forfeiting_team_invalid()
    apply_forfeit_effects(game, forfeiting_team_id, manual=True)
    return envelope_object(game_out(game))
