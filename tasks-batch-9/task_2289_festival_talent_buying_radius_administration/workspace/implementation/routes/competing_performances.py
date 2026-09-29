"""Competing-performance reporting, conflict detection and adjudication."""

from flask import Blueprint, g

from db import db, new_row, public, public_list, touch
from errors import fail
from middleware import endpoint, is_artist_rep, require_artist_scope
from response import paginate, respond_array, respond_object
from services import calc, derive
from validators import (
    body,
    body_fk,
    date_str,
    load,
    opt_int,
    opt_string,
    pagination,
    query_enum,
    query_string,
    req_bool,
    req_date,
    req_enum,
    req_number,
    req_string,
    stored_date,
)

bp = Blueprint("competing_performances", __name__)

PERF_STATUSES = ("REPORTED", "CLEARED", "VIOLATION", "WAIVED")
ASSESSMENTS = ("NO_CONFLICT", "CONFLICT")


@bp.post("/competing-performances")
@endpoint(["TalentBuyer", "BusinessAffairs"])
def create_performance():
    payload = body()
    req_string(payload, "artist_id", 1)
    venue_city = req_string(payload, "venue_city", 1, 80)
    venue_latitude = req_number(payload, "venue_latitude", -90.0, 90.0)
    venue_longitude = req_number(payload, "venue_longitude", -180.0, 180.0)
    performance_date = req_date(payload, "performance_date")
    is_ticketed = req_bool(payload, "is_ticketed")
    is_festival = req_bool(payload, "is_festival")
    announced_capacity = opt_int(payload, "announced_capacity", 0, 0, None)

    artist = body_fk(payload, "artist_id", "artists")

    row = new_row(
        artist_id=artist["id"],
        venue_city=venue_city,
        venue_latitude=venue_latitude,
        venue_longitude=venue_longitude,
        performance_date=date_str(performance_date),
        is_ticketed=is_ticketed,
        is_festival=is_festival,
        announced_capacity=announced_capacity,
        distance_to_market_miles=None,
        conflict_assessment="NO_CONFLICT",
        conflicting_radius_clause_id=None,
        status="REPORTED",
        reported_by_user_id=g.user_id,
    )
    db.competing_performances[row["id"]] = row

    clause, distance = calc.detect_conflict(row)
    if clause is not None:
        row["conflict_assessment"] = "CONFLICT"
        row["conflicting_radius_clause_id"] = clause["id"]
        row["distance_to_market_miles"] = float(distance)
        if derive.recompute_artist(artist):
            touch(artist)

    row["version"] = 1
    row["updated_at"] = row["created_at"]
    return respond_object(public(row), 201)


@bp.get("/competing-performances/<performance_id>")
@endpoint(["TalentBuyer", "ArtistRep", "BusinessAffairs"])
def get_performance(performance_id):
    row = load("competing_performances", performance_id)
    require_artist_scope(row["artist_id"])
    return respond_object(public(row))


@bp.get("/competing-performances")
@endpoint(["TalentBuyer", "ArtistRep", "BusinessAffairs"])
def list_performances():
    artist_id = query_string("artist_id")
    clause_id = query_string("conflicting_radius_clause_id")
    status = query_enum("status", PERF_STATUSES)
    assessment = query_enum("conflict_assessment", ASSESSMENTS)
    limit, offset = pagination()

    rows = list(db.competing_performances.values())
    if is_artist_rep():
        rows = [r for r in rows if r["artist_id"] == g.user_id]
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if clause_id is not None:
        rows = [r for r in rows if r["conflicting_radius_clause_id"] == clause_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if assessment is not None:
        rows = [r for r in rows if r["conflict_assessment"] == assessment]

    rows = sorted(rows, key=lambda r: r["_seq"])
    rows = sorted(rows, key=lambda r: stored_date(r["performance_date"]))
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.post("/competing-performances/<performance_id>/adjudicate")
@endpoint(["BusinessAffairs"])
def adjudicate(performance_id):
    payload = body()
    finding = req_enum(payload, "finding", ("CLEARED", "VIOLATION"))
    opt_string(payload, "finding_note", None, 1, None)

    row = load("competing_performances", performance_id)
    if row["status"] != "REPORTED":
        fail(
            "ERR_PERFORMANCE_ALREADY_ADJUDICATED",
            "this report has already been adjudicated",
        )

    if finding == "CLEARED":
        row["status"] = "CLEARED"
        touch(row)
        artist = db.artists.get(row["artist_id"])
        if artist is not None and derive.recompute_artist(artist):
            touch(artist)
        return respond_object(public(row))

    clause = None
    if row["conflict_assessment"] == "CONFLICT" and row["conflicting_radius_clause_id"]:
        clause = db.radius_clauses.get(row["conflicting_radius_clause_id"])
    if clause is None:
        fail(
            "ERR_ADJUDICATION_MISMATCH",
            "a violation finding needs a report that detected a conflict",
        )

    derive.cascade_violation(row, clause)
    return respond_object(public(row))
