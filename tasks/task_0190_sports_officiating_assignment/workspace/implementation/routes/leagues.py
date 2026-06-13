"""League endpoints (PRD §3.1).

POST   /leagues
GET    /leagues
GET    /leagues/{id}
GET    /leagues/{id}/season-ledgers
POST   /leagues/{id}/activate         SETUP -> OPEN
POST   /leagues/{id}/start-postseason OPEN  -> POSTSEASON (+ eligibility cascade)
POST   /leagues/{id}/archive          POSTSEASON -> ARCHIVED
"""
from flask import Blueprint

import db
import lookup
import serialize
from errors import err, ERR_INVALID_STATE
from middleware import get_user_context, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response
from services import validate, derive

bp = Blueprint("leagues", __name__)

SPORTS = {"BASKETBALL", "SOCCER", "HOCKEY", "FOOTBALL"}
READ_ROLES = {"LeagueAdmin", "Assignor", "Official", "Evaluator"}


@bp.route("/leagues", methods=["POST"])
def create_league():
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    data = validate.body()
    name = validate.require_str(data, "name")
    sport = validate.enum(data, "sport", SPORTS)
    base_fee = validate.integer(data, "base_game_fee_cents", minimum=0)
    mileage_rate = validate.integer(data, "mileage_rate_cents_per_mile", minimum=0)
    min_games = validate.integer(data, "postseason_min_games", required=False,
                                 default=8, minimum=0)
    min_rating = validate.number(data, "postseason_min_rating", required=False,
                                 default=3.5)
    max_noshows = validate.integer(data, "postseason_max_noshows", required=False,
                                   default=0, minimum=0)
    with db.lock:
        rec = {
            "name": name,
            "sport": sport,
            "base_game_fee_cents": base_fee,
            "mileage_rate_cents_per_mile": mileage_rate,
            "postseason_min_games": min_games,
            "postseason_min_rating": min_rating,
            "postseason_max_noshows": max_noshows,
            "status": "SETUP",
        }
        db.stamp_create(rec)
        db.leagues[rec["id"]] = rec
    return object_response(serialize.league(rec), 201)


@bp.route("/leagues", methods=["GET"])
def list_leagues():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        page, total = paginate(list(db.leagues.values()), limit, offset)
        items = [serialize.league(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/leagues/<league_id>", methods=["GET"])
def get_league(league_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.league(league_id)
        return object_response(serialize.league(rec))


@bp.route("/leagues/<league_id>/season-ledgers", methods=["GET"])
def list_league_ledgers(league_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        lookup.league(league_id)
        rows = [l for l in db.season_ledgers.values() if l["league_id"] == league_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.ledger(r) for r in page]
    return array_response(items, limit, offset, total)


def _transition(league_id, from_state, to_state):
    rec = lookup.league(league_id)
    if rec["status"] != from_state:
        err(ERR_INVALID_STATE, "league not in %s" % from_state)
    rec["status"] = to_state
    db.touch(rec)
    return rec


@bp.route("/leagues/<league_id>/activate", methods=["POST"])
def activate_league(league_id):
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    with db.lock:
        rec = _transition(league_id, "SETUP", "OPEN")
        return object_response(serialize.league(rec))


@bp.route("/leagues/<league_id>/start-postseason", methods=["POST"])
def start_postseason(league_id):
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    with db.lock:
        rec = _transition(league_id, "OPEN", "POSTSEASON")
        # Cascade: recompute postseason_eligible for every official in league.
        for off in db.officials.values():
            if off["league_id"] == league_id:
                derive.recompute_official_derived(off)
        return object_response(serialize.league(rec))


@bp.route("/leagues/<league_id>/archive", methods=["POST"])
def archive_league(league_id):
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    with db.lock:
        rec = _transition(league_id, "POSTSEASON", "ARCHIVED")
        return object_response(serialize.league(rec))
