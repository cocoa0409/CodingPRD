"""Players, rating assignment and the per-player committee-vote listing."""

from decimal import Decimal

from flask import Blueprint

import derive
from auth import authenticate, require_self
from errors import ApiError
from response import object_response
from routes_common import (ALL_ROLES, ROLE_COMMITTEE_CHAIR, ROLE_COMMITTEE_MEMBER,
                           ROLE_LEAGUE_COORDINATOR, ROLE_PLAYER, ROLE_SECTION_ADMIN,
                           ROLE_CAPTAIN, found, listing, reference)
from store import db, insert, new_id, now_iso, public, touch
from validation import (bad, body, check_level, opt_string, reject_unknown, req_enum, req_int,
                        req_level, req_string, to_level)

bp = Blueprint("player", __name__, url_prefix="/tennis")

PLAYER_CREATE_ROLES = (ROLE_SECTION_ADMIN, ROLE_LEAGUE_COORDINATOR)
PLAYER_LIST_ROLES = (ROLE_SECTION_ADMIN, ROLE_LEAGUE_COORDINATOR, ROLE_CAPTAIN,
                     ROLE_COMMITTEE_MEMBER, ROLE_COMMITTEE_CHAIR)
RATING_ROLES = (ROLE_PLAYER, ROLE_LEAGUE_COORDINATOR)
VOTE_READ_ROLES = (ROLE_SECTION_ADMIN, ROLE_COMMITTEE_CHAIR, ROLE_COMMITTEE_MEMBER)
GENDERS = ("M", "F")
RATING_SOURCES = ("SELF", "COMPUTER")


@bp.post("/players")
def create_player():
    authenticate(PLAYER_CREATE_ROLES)
    payload = body()
    raw_section = payload.get("section_id")
    section = None
    if isinstance(raw_section, str) and raw_section.strip():
        section = reference("sections", raw_section.strip())
    reject_unknown(payload, {"section_id", "full_name", "birth_year", "gender"})
    req_string(payload, "section_id", 1)
    full_name = req_string(payload, "full_name", 1)
    birth_year = req_int(payload, "birth_year", 1900, 2020)
    gender = req_enum(payload, "gender", GENDERS)
    if section is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    record = {
        "id": new_id(),
        "section_id": section["id"],
        "full_name": full_name,
        "birth_year": birth_year,
        "gender": gender,
        "rating_level": None,
        "rating_type": "UNRATED",
        "self_rated_level": None,
        "dynamic_rating": None,
        "verified_match_count": 0,
        "verified_line_count": 0,
        "strike_count": 0,
        "status": "ACTIVE",
        "proposed_recalc_level": None,
        "proposed_recalc_dynamic": None,
        "rating_history": [],
    }
    insert("players", record)
    return object_response(public(record), 201)


@bp.get("/players/<player_id>")
def get_player(player_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("players", player_id)))


@bp.get("/players")
def list_players():
    authenticate(PLAYER_LIST_ROLES)
    spec = {"section_id": ("section_id", "str"), "status": ("status", "str"),
            "rating_type": ("rating_type", "str"), "gender": ("gender", "str")}
    return listing(db.players.values(), spec)


@bp.post("/players/<player_id>/ratings")
def assign_rating(player_id):
    actor = authenticate(RATING_ROLES)
    require_self(actor, player_id)
    player = found("players", player_id)
    payload = body()
    reject_unknown(payload, {"source", "level"})
    source = req_enum(payload, "source", RATING_SOURCES)
    level = req_level(payload, "level")

    if source == "SELF" and actor.role != ROLE_PLAYER:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if source == "COMPUTER" and actor.role != ROLE_LEAGUE_COORDINATOR:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    check_level(level)

    section = db.sections.get(player.get("section_id")) or {}
    if section.get("rating_period_status") != "OPEN_SEASON":
        raise ApiError("ERR_RATING_PERIOD_CLOSED")

    if source == "SELF":
        if player.get("rating_type") not in ("UNRATED", "SELF_RATED"):
            raise ApiError("ERR_SELF_RATING_LOCKED")
        player["rating_level"] = float(level)
        player["self_rated_level"] = float(level)
        player["rating_type"] = "SELF_RATED"
        history_source = "SELF"
    else:
        player["rating_level"] = float(level)
        player["rating_type"] = "COMPUTER_RATED"
        history_source = "COMPUTER"

    derive.append_rating_history(player, history_source, level, player.get("dynamic_rating"),
                                 section.get("season_year"), now_iso())
    touch(player)
    return object_response(public(player))


@bp.get("/players/<player_id>/committee-votes")
def list_player_votes(player_id):
    authenticate(VOTE_READ_ROLES)
    found("players", player_id)
    rows = [v for v in db.committee_votes.values() if v.get("voter_player_id") == player_id]
    return listing(rows, {"subject_type": ("subject_type", "str")})
