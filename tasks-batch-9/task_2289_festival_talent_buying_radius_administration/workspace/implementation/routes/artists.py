"""Roster act routes, plus the logical clock endpoint."""

from flask import Blueprint

from db import db, iso_instant, new_row, public
from errors import fail
from middleware import ALL_ROLES, endpoint, require_artist_scope
from response import respond_object
from services import calc
from validators import (
    body,
    load,
    opt_int,
    query_enum,
    req_enum,
    req_instant,
    req_int,
    req_string,
)

bp = Blueprint("artists", __name__)

GENRES = ("ELECTRONIC", "HIP_HOP", "ROCK", "POP", "LATIN", "JAZZ_SOUL", "COUNTRY")


@bp.post("/artists")
@endpoint(["TalentBuyer"])
def create_artist():
    payload = body()
    legal_name = req_string(payload, "legal_name", 1, 120)
    performing_name = req_string(payload, "performing_name", 1, 120)
    primary_genre = req_enum(payload, "primary_genre", GENRES)
    agency = req_string(payload, "agency", 1, 120)
    draw_score = req_int(payload, "draw_score", 0, 100)
    default_radius_miles = opt_int(payload, "default_radius_miles", 75, 0, 500)

    for artist in db.artists.values():
        if artist["performing_name"] == performing_name:
            fail("ERR_DUPLICATE_ARTIST_NAME", "performing_name is globally unique")

    row = new_row(
        legal_name=legal_name,
        performing_name=performing_name,
        primary_genre=primary_genre,
        agency=agency,
        draw_score=draw_score,
        default_radius_miles=default_radius_miles,
        reported_conflict_count=0,
        radius_breach_count=0,
        strict_risk_score=0,
        adjudicated_risk_score=0,
    )
    db.artists[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/artists/<artist_id>")
@endpoint(
    [
        "TalentBuyer",
        "ArtistRep",
        "BusinessAffairs",
        "ProductionManager",
        "FinanceController",
    ]
)
def get_artist(artist_id):
    artist = load("artists", artist_id)
    require_artist_scope(artist["id"])
    return respond_object(public(artist))


@bp.get("/artists/<artist_id>/radius-risk")
@endpoint(["TalentBuyer", "ArtistRep", "BusinessAffairs"])
def artist_radius_risk(artist_id):
    variant = query_enum("variant", ("STRICT", "ADJUDICATED")) or "STRICT"
    artist = load("artists", artist_id)
    require_artist_scope(artist["id"])

    parts = calc.risk_components(artist)
    score = (
        parts["strict_risk_score"]
        if variant == "STRICT"
        else parts["adjudicated_risk_score"]
    )
    return respond_object(
        {
            "variant": variant,
            "reported_conflict_count": parts["reported_conflict_count"],
            "radius_breach_count": parts["radius_breach_count"],
            "draw_penalty": parts["draw_penalty"],
            "risk_score": score,
            "blocked": score >= calc.RISK_BLOCK_THRESHOLD,
        }
    )


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_clock():
    payload = body()
    current_utc = req_instant(payload, "current_utc")
    db.clock = current_utc
    return respond_object({"current_utc": iso_instant(current_utc)})
