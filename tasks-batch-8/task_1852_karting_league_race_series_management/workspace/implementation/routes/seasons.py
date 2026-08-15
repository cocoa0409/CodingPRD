"""Seasons, classes, and standings routes."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEASON_NOT_ACTIVE,
    ERR_DUPLICATE_CLASS_CODE,
)
from middleware import authorized, ANY_ROLE
from response import success_object, success_array
from services import core
from services.calculations import compute_standings
from validate import json_body, v_str, v_int, v_num, v_bool, v_enum, v_int_list

bp = Blueprint("seasons", __name__)


@bp.post("/seasons")
def create_season():
    authorized(["LeagueAdmin"])
    body = json_body()
    name = v_str(body, "name")
    year = v_int(body, "year")
    drop_rounds = v_int(body, "drop_rounds", required=False, default=0, min_val=0)
    points_scheme = v_int_list(body, "points_scheme")
    bonus = v_int(body, "fastest_lap_bonus_points", required=False, default=0)
    season = core.create_record("seasons", {
        "name": name,
        "year": year,
        "drop_rounds": drop_rounds,
        "points_scheme": list(points_scheme),
        "fastest_lap_bonus_points": bonus,
        "status": "SCHEDULED",
    })
    return success_object(core.serialize_season(season), 201)


@bp.get("/seasons/<season_id>")
def get_season(season_id):
    authorized(ANY_ROLE)
    season = core.must_find("seasons", season_id, "season not found")
    return success_object(core.serialize_season(season))


@bp.post("/seasons/<season_id>/activate")
def activate_season(season_id):
    authorized(["LeagueAdmin"])
    season = core.must_find("seasons", season_id, "season not found")
    if season["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "season is not SCHEDULED")
    has_class = any(c["season_id"] == season["id"] for c in core.db["classes"].values())
    if not has_class:
        raise_error(ERR_INVALID_STATE, "season has no race classes")
    season["status"] = "ACTIVE"
    core.touch(season)
    return success_object(core.serialize_season(season))


@bp.post("/seasons/<season_id>/finalize")
def finalize_season(season_id):
    authorized(["LeagueAdmin"])
    season = core.must_find("seasons", season_id, "season not found")
    if season["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "season is not ACTIVE")
    has_finalized_event = any(
        e["season_id"] == season["id"] and e["status"] == "FINALIZED"
        for e in core.db["events"].values()
    )
    if not has_finalized_event:
        raise_error(ERR_INVALID_STATE, "season has no FINALIZED event")
    season["status"] = "FINALIZED"
    core.touch(season)
    return success_object(core.serialize_season(season))


@bp.post("/seasons/<season_id>/conclude-awards")
def conclude_awards(season_id):
    authorized(["LeagueAdmin"])
    season = core.must_find("seasons", season_id, "season not found")
    if season["status"] != "FINALIZED":
        raise_error(ERR_INVALID_STATE, "season is not FINALIZED")
    season["status"] = "AWARDS_CONCLUDED"
    core.touch(season)
    return success_object(core.serialize_season(season))


@bp.get("/seasons/<season_id>/standings")
def get_standings(season_id):
    authorized(ANY_ROLE)
    season = core.must_find("seasons", season_id, "season not found")
    class_id = request.args.get("class_id")
    if not class_id:
        raise_error(ERR_INVALID_REQUEST, "query parameter class_id is required")
    race_class = core.find("classes", class_id)
    if race_class is None or race_class["season_id"] != season["id"]:
        raise_error(ERR_NOT_FOUND, "class not found in this season")
    rows = compute_standings(season, race_class)
    return success_object({
        "season_id": season["id"],
        "class_id": race_class["id"],
        "rows": rows,
    })


# --- classes (nested under seasons) --------------------------------------------

def _check_class_creation_gate(season):
    """Class creation: allowed in SCHEDULED/ACTIVE; FINALIZED refused as
    ERR_SEASON_NOT_ACTIVE; AWARDS_CONCLUDED locks the season (ERR_INVALID_STATE)."""
    if season["status"] == "AWARDS_CONCLUDED":
        raise_error(ERR_INVALID_STATE, "season is locked after awards conclusion")
    if season["status"] not in ("SCHEDULED", "ACTIVE"):
        raise_error(ERR_SEASON_NOT_ACTIVE, "season is not ACTIVE")


@bp.post("/seasons/<season_id>/classes")
def create_class(season_id):
    authorized(["LeagueAdmin"])
    body = json_body()
    code = v_enum(body, "code", core.CLASS_CODES)
    min_age = v_int(body, "min_age")
    max_age = v_int(body, "max_age")
    min_weight = v_num(body, "min_combined_weight_kg", gt=0)
    entry_fee = v_int(body, "entry_fee_cents", min_val=0)
    rental_allowed = v_bool(body, "rental_kart_allowed")
    season = core.must_find("seasons", season_id, "season not found")
    _check_class_creation_gate(season)
    for c in core.db["classes"].values():
        if c["season_id"] == season["id"] and c["code"] == code:
            raise_error(ERR_DUPLICATE_CLASS_CODE, "class code already exists in the season")
    race_class = core.create_record("classes", {
        "season_id": season["id"],
        "code": code,
        "min_age": min_age,
        "max_age": max_age,
        "min_combined_weight_kg": min_weight,
        "entry_fee_cents": entry_fee,
        "rental_kart_allowed": rental_allowed,
    })
    return success_object(core.serialize_class(race_class), 201)


@bp.get("/seasons/<season_id>/classes")
def list_classes(season_id):
    authorized(ANY_ROLE)
    season = core.must_find("seasons", season_id, "season not found")
    items = [c for c in core.db["classes"].values() if c["season_id"] == season["id"]]
    return success_array([core.serialize_class(c) for c in core.list_sorted(items)])


@bp.get("/classes/<class_id>")
def get_class(class_id):
    authorized(ANY_ROLE)
    race_class = core.must_find("classes", class_id, "class not found")
    return success_object(core.serialize_class(race_class))
