"""Season endpoints (PRD §3.1)."""

from flask import Blueprint

import db
import domain
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND
from helpers import (
    get_body,
    check_no_undeclared,
    ok_object,
    paginate,
    req_date,
    req_str,
    opt_str,
    require,
)

bp = Blueprint("seasons", __name__)

FM = ("FarmManager",)
READERS = ("FarmManager", "GateStaff", "FieldStaff", "KioskDevice")


@bp.post("/farm/seasons")
def create_season():
    require(FM)
    body = get_body()
    check_no_undeclared(body, {"name", "start_date", "end_date", "waiver_text"})
    name = req_str(body, "name")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    waiver_text = req_str(body, "waiver_text")
    if end_date < start_date:
        raise_err(ERR_INVALID_REQUEST, "end_date must be >= start_date")
    season = domain.new_entity()
    season.update(
        {
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "waiver_text": waiver_text,
            "current_waiver_version": 1,
            "status": "DRAFT",
        }
    )
    db.seasons[season["id"]] = season
    return ok_object(domain.serialize_season(season), 201)


@bp.get("/farm/seasons/<sid>")
def get_season(sid):
    require(READERS)
    season = db.seasons.get(sid)
    if season is None:
        raise_err(ERR_NOT_FOUND, "Season not found")
    return ok_object(domain.serialize_season(season))


@bp.post("/farm/seasons/<sid>/activate")
def activate_season(sid):
    require(FM)
    season = db.seasons.get(sid)
    if season is None:
        raise_err(ERR_NOT_FOUND, "Season not found")
    if season["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT season can be activated")
    for other in db.seasons.values():
        if other["id"] != sid and other["status"] == "ACTIVE":
            raise_err(ERR_INVALID_STATE, "Another season is currently ACTIVE")
    season["status"] = "ACTIVE"
    domain.touch(season)
    return ok_object(domain.serialize_season(season))


@bp.post("/farm/seasons/<sid>/archive")
def archive_season(sid):
    require(FM)
    season = db.seasons.get(sid)
    if season is None:
        raise_err(ERR_NOT_FOUND, "Season not found")
    if season["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE season can be archived")
    for f in db.fields.values():
        if f["season_id"] == sid and f["status"] in ("OPEN", "PICKED_OUT"):
            raise_err(
                ERR_INVALID_STATE,
                "All fields must be RETIRED, DORMANT, or ROTATION_REST to archive",
            )
    for d in db.sales_days.values():
        if d["season_id"] == sid and d["status"] == "OPEN":
            raise_err(ERR_INVALID_STATE, "A SalesDay of this season is OPEN")
    season["status"] = "ARCHIVED"
    domain.touch(season)
    return ok_object(domain.serialize_season(season))


@bp.post("/farm/seasons/<sid>/config")
def config_season(sid):
    require(FM)
    season = db.seasons.get(sid)
    if season is None:
        raise_err(ERR_NOT_FOUND, "Season not found")
    body = get_body()
    check_no_undeclared(body, {"waiver_text", "name"})
    waiver_text = opt_str(body, "waiver_text")
    name = opt_str(body, "name")
    if waiver_text is None and name is None:
        raise_err(ERR_INVALID_REQUEST, "Provide waiver_text and/or name")
    if waiver_text is not None and waiver_text != season["waiver_text"]:
        season["waiver_text"] = waiver_text
        season["current_waiver_version"] += 1
    if name is not None:
        season["name"] = name
    domain.touch(season)
    return ok_object(domain.serialize_season(season))
