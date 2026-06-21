"""Inspection logistics: reading rooms, review stations, and their bookings.

Two distinct interval geometries (PRD §3.9):
  - Reading room: half-open intervals [s, e), aggregate-capacity. Reject when at
    some instant in [s, e) the count of existing room bookings active there is
    >= capacity. Touching endpoints never conflict.
  - Review station: closed intervals [s, e] + single occupancy + buffer. Reject
    when new comes within buffer_minutes of any existing booking on the station.
"""

from datetime import timedelta

from flask import Blueprint, request as flask_request

import db
from clock import parse_iso
from errors import (
    api_error,
    ERR_INVALID_REQUEST, ERR_ROOM_AT_CAPACITY, ERR_STATION_BUFFER_CONFLICT,
)
from helpers import (
    get_json_body, require_str, require_int, get_or_404, fk_or_404,
    serialize, parse_pagination, sort_by_creation, paginate,
)
from middleware import require_roles
from response import ok_object, ok_array

bp = Blueprint("bookings", __name__)


# ---- Reading rooms ---------------------------------------------------------
@bp.post("/reading-rooms")
def register_room():
    require_roles("FoiaOfficer")
    body = get_json_body()
    name = require_str(body, "name")
    capacity = require_int(body, "capacity", minimum=1)
    obj = {"name": name, "capacity": capacity}
    db.stamp_create(obj)
    db.reading_rooms[obj["id"]] = obj
    return ok_object(serialize("ReadingRoom", obj), status=201)


@bp.get("/reading-rooms/<room_id>")
def get_room(room_id):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.reading_rooms, room_id)
    return ok_object(serialize("ReadingRoom", obj), status=200)


# ---- Review stations -------------------------------------------------------
@bp.post("/review-stations")
def register_station():
    require_roles("FoiaOfficer")
    body = get_json_body()
    name = require_str(body, "name")
    buffer_minutes = require_int(body, "buffer_minutes", minimum=0)
    obj = {"name": name, "buffer_minutes": buffer_minutes}
    db.stamp_create(obj)
    db.review_stations[obj["id"]] = obj
    return ok_object(serialize("ReviewStation", obj), status=201)


@bp.get("/review-stations/<station_id>")
def get_station(station_id):
    require_roles("FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.review_stations, station_id)
    return ok_object(serialize("ReviewStation", obj), status=200)


def _parse_interval(body):
    starts_at = require_str(body, "starts_at")
    ends_at = require_str(body, "ends_at")
    s = parse_iso(starts_at)
    e = parse_iso(ends_at)
    if s is None or e is None:
        raise api_error(ERR_INVALID_REQUEST, "starts_at and ends_at must be valid ISO 8601 instants.")
    if not (e > s):
        raise api_error(ERR_INVALID_REQUEST, "ends_at must be strictly after starts_at.")
    return starts_at, ends_at, s, e


# ---- Reading-room bookings -------------------------------------------------
@bp.post("/reading-rooms/<room_id>/bookings")
def book_room(room_id):
    require_roles("Requester", "FoiaOfficer")
    room = get_or_404(db.reading_rooms, room_id)
    body = get_json_body()
    # Body-FK existence (priority 5) before remaining structural validity (6).
    request_id = require_str(body, "request_id")
    fk_or_404(db.requests, request_id)
    starts_at, ends_at, s, e = _parse_interval(body)

    # Aggregate-capacity, half-open overlap. Two intervals overlap iff
    # a.start < b.end AND b.start < a.end. The peak concurrent count over the
    # new interval among overlapping existing bookings must stay < capacity;
    # equivalently, reject if at some covered instant the count of existing
    # active bookings is >= capacity. Candidate instants are the new start and
    # each existing start that falls within [s, e).
    existing = [b for b in db.reading_room_bookings.values() if b["room_id"] == room_id]
    parsed = [(parse_iso(b["starts_at"]), parse_iso(b["ends_at"])) for b in existing]

    candidate_instants = [s]
    for (bs, be) in parsed:
        if s <= bs < e:
            candidate_instants.append(bs)

    for t in candidate_instants:
        active = sum(1 for (bs, be) in parsed if bs <= t < be)
        if active >= room["capacity"]:
            raise api_error(ERR_ROOM_AT_CAPACITY, "Reading room is at capacity for some instant of the booking.")

    obj = {"room_id": room_id, "request_id": request_id, "starts_at": starts_at, "ends_at": ends_at}
    db.stamp_create(obj)
    db.reading_room_bookings[obj["id"]] = obj
    return ok_object(serialize("ReadingRoomBooking", obj), status=201)


@bp.get("/reading-rooms/<room_id>/bookings")
def list_room_bookings(room_id):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    get_or_404(db.reading_rooms, room_id)
    limit, offset = parse_pagination()
    items = sort_by_creation([b for b in db.reading_room_bookings.values() if b["room_id"] == room_id])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("ReadingRoomBooking", b) for b in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.get("/reading-room-bookings/<bid>")
def get_room_booking(bid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.reading_room_bookings, bid)
    return ok_object(serialize("ReadingRoomBooking", obj), status=200)


@bp.get("/reading-room-bookings")
def list_all_room_bookings():
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    limit, offset = parse_pagination()
    request_id = flask_request.args.get("request_id")
    room_id = flask_request.args.get("room_id")
    items = list(db.reading_room_bookings.values())
    if request_id is not None:
        items = [b for b in items if b["request_id"] == request_id]
    if room_id is not None:
        items = [b for b in items if b["room_id"] == room_id]
    items = sort_by_creation(items)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("ReadingRoomBooking", b) for b in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


# ---- Review-station bookings ------------------------------------------------
@bp.post("/review-stations/<station_id>/bookings")
def book_station(station_id):
    require_roles("FoiaOfficer")
    station = get_or_404(db.review_stations, station_id)
    body = get_json_body()
    # Body-FK existence (priority 5) before remaining structural validity (6).
    request_id = require_str(body, "request_id")
    fk_or_404(db.requests, request_id)
    starts_at, ends_at, s, e = _parse_interval(body)

    buffer_delta = timedelta(minutes=station["buffer_minutes"])
    existing = [b for b in db.review_station_bookings.values() if b["station_id"] == station_id]
    for b in existing:
        bs = parse_iso(b["starts_at"])
        be = parse_iso(b["ends_at"])
        # reject if new.start <= existing.end + buffer AND existing.start <= new.end + buffer
        if s <= be + buffer_delta and bs <= e + buffer_delta:
            raise api_error(ERR_STATION_BUFFER_CONFLICT,
                            "Review-station booking falls within the buffer of an existing booking.")

    obj = {"station_id": station_id, "request_id": request_id, "starts_at": starts_at, "ends_at": ends_at}
    db.stamp_create(obj)
    db.review_station_bookings[obj["id"]] = obj
    return ok_object(serialize("ReviewStationBooking", obj), status=201)


@bp.get("/review-stations/<station_id>/bookings")
def list_station_bookings(station_id):
    require_roles("FoiaOfficer", "AppealAuthority")
    get_or_404(db.review_stations, station_id)
    limit, offset = parse_pagination()
    items = sort_by_creation([b for b in db.review_station_bookings.values() if b["station_id"] == station_id])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("ReviewStationBooking", b) for b in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.get("/review-station-bookings/<bid>")
def get_station_booking(bid):
    require_roles("FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.review_station_bookings, bid)
    return ok_object(serialize("ReviewStationBooking", obj), status=200)


@bp.get("/review-station-bookings")
def list_all_station_bookings():
    require_roles("FoiaOfficer", "AppealAuthority")
    limit, offset = parse_pagination()
    request_id = flask_request.args.get("request_id")
    station_id = flask_request.args.get("station_id")
    items = list(db.review_station_bookings.values())
    if request_id is not None:
        items = [b for b in items if b["request_id"] == request_id]
    if station_id is not None:
        items = [b for b in items if b["station_id"] == station_id]
    items = sort_by_creation(items)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("ReviewStationBooking", b) for b in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)
