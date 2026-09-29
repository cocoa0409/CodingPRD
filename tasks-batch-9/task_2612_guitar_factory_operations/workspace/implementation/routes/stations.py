"""Stations, the work selector and station reservations (PRD 3.4)."""

from flask import Blueprint

import auth
import calc
import domain
import store
import validate as v
from constants import RESERVATION_STATUSES, STATION_TYPES
from envelope import object_response, paginate
from errors import ApiError
from serialize import reservation_view, station_view
from store import (COMPONENTS, ORDERS, RESERVATIONS, ROOMS, STATIONS,
                   fmt_ts, new_record, now_utc)

bp = Blueprint("stations", __name__)


@bp.post("/stations")
def create_station():
    auth.require(auth.PLANT_ADMIN)
    body = v.body()
    station_code = v.get_str(body, "station_code", min_len=1, max_len=64)
    station_type = v.get_enum(body, "station_type", STATION_TYPES)
    room_id = v.get_id(body, "room_id")
    changeover = v.get_int(body, "changeover_minutes", required=False,
                           minimum=0, default=30)
    room = v.fetch(ROOMS, room_id, "ERR_STORAGE_ROOM_NOT_FOUND")
    v.unique_code(STATIONS, "station_code", station_code)
    if room["climate_status"] == "QUARANTINED":
        raise ApiError("ERR_ROOM_QUARANTINED", "the room is quarantined")
    rec = new_record(STATIONS, {
        "station_code": station_code,
        "station_type": station_type,
        "room_id": room_id,
        "changeover_minutes": changeover,
        "total_scheduled_minutes": 0,
        "held_minutes": 0,
        "consumed_minutes": 0,
        "released_minutes": 0,
    })
    return object_response(station_view(rec), 201)


@bp.get("/stations/<station_id>")
def read_station(station_id):
    auth.require_staff()
    return object_response(station_view(
        v.fetch(STATIONS, station_id, "ERR_STATION_NOT_FOUND")))


@bp.get("/stations")
def list_stations():
    auth.require_staff()
    rows = v.apply_filters(list(STATIONS.values()), [
        ("room_id", v.filter_value("room_id")),
        ("station_type", v.filter_enum("station_type", STATION_TYPES)),
    ])
    rows.sort(key=lambda r: r["station_code"])
    return paginate(rows, station_view)


@bp.get("/stations/<station_id>/next-build-order")
def next_build_order(station_id):
    auth.require(auth.MACHINIST, auth.LUTHIER, auth.PLANT_ADMIN)
    station = v.fetch(STATIONS, station_id, "ERR_STATION_NOT_FOUND")
    pool = []
    for order in ORDERS.values():
        if order["build_stage"] in ("SERIALIZED", "SCRAPPED",
                                    "COMPLIANCE_HOLD"):
            continue
        if order["commercial_status"] in ("QUOTED", "INVOICED", "CLOSED",
                                         "CANCELLED"):
            continue
        starts = [r["starts_at"] for r in RESERVATIONS.values()
                  if r["station_id"] == station["id"]
                  and r["build_order_id"] == order["id"]
                  and r["status"] == "HELD"]
        if not starts:
            continue
        # the selector refreshes a stale score as it reads
        order["priority_score"] = calc.priority_score(order)
        pool.append((order, min(starts)))
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_BUILD_ORDER",
                       "no eligible build order holds time on this station")
    pool.sort(key=lambda item: (-item[0]["priority_score"], item[1],
                                item[0]["created_at"], item[0]["_seq"]))
    winner, starts_at = pool[0]
    return object_response({
        "build_order_id": winner["id"],
        "order_code": winner["order_code"],
        "priority_score": float(winner["priority_score"]),
        "starts_at": fmt_ts(starts_at),
        "eligible_count": len(pool),
    })


@bp.post("/station-reservations")
def create_reservation():
    auth.require(auth.MACHINIST, auth.LUTHIER)
    body = v.body()
    station_id = v.get_id(body, "station_id")
    starts_at = v.get_ts(body, "starts_at")
    ends_at = v.get_ts(body, "ends_at")
    order_id = v.get_id(body, "build_order_id", required=False)
    component_id = v.get_id(body, "component_id", required=False)
    if starts_at >= ends_at:
        raise ApiError("ERR_INVALID_WINDOW",
                       "starts_at must be strictly earlier than ends_at")
    duration = int((ends_at - starts_at).total_seconds() // 60)
    if duration <= 0:
        v.bad("the window is shorter than one whole minute")

    station = v.fetch(STATIONS, station_id, "ERR_STATION_NOT_FOUND")
    order = v.fetch(ORDERS, order_id, "ERR_BUILD_ORDER_NOT_FOUND") \
        if order_id else None
    component = v.fetch(COMPONENTS, component_id, "ERR_COMPONENT_NOT_FOUND") \
        if component_id else None

    room = ROOMS.get(station["room_id"])
    if room is not None and room["climate_status"] == "QUARANTINED":
        raise ApiError("ERR_ROOM_QUARANTINED",
                       "the station stands in a quarantined room")
    if order is not None and component is not None \
            and component["build_order_id"] != order["id"]:
        raise ApiError("ERR_RESERVATION_COMPONENT_MISMATCH",
                       "the component does not belong to that build order")
    if domain.station_conflict(station, starts_at, ends_at) is not None:
        raise ApiError("ERR_STATION_WINDOW_CONFLICT",
                       "the window collides with an existing booking")

    rec = new_record(RESERVATIONS, {
        "station_id": station_id,
        "build_order_id": order_id,
        "component_id": component_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "duration_minutes": duration,
        "priority_score": order["priority_score"] if order else None,
        "status": "HELD",
    })
    domain.station_book(station, duration)
    return object_response(reservation_view(rec), 201)


@bp.get("/station-reservations/<reservation_id>")
def read_reservation(reservation_id):
    auth.require_staff()
    return object_response(reservation_view(
        v.fetch(RESERVATIONS, reservation_id,
                "ERR_STATION_RESERVATION_NOT_FOUND")))


@bp.get("/station-reservations")
def list_reservations():
    auth.require_staff()
    rows = v.apply_filters(list(RESERVATIONS.values()), [
        ("station_id", v.filter_value("station_id")),
        ("build_order_id", v.filter_value("build_order_id")),
        ("component_id", v.filter_value("component_id")),
        ("status", v.filter_enum("status", RESERVATION_STATUSES)),
    ])
    rows.sort(key=lambda r: (r["starts_at"], r["created_at"], r["_seq"]))
    return paginate(rows, reservation_view)


@bp.post("/station-reservations/<reservation_id>/release")
def release_reservation(reservation_id):
    auth.require(auth.MACHINIST, auth.LUTHIER, auth.PLANT_ADMIN)
    rec = v.fetch(RESERVATIONS, reservation_id,
                  "ERR_STATION_RESERVATION_NOT_FOUND")
    if rec["status"] != "HELD":
        raise ApiError("ERR_RESERVATION_STATE_INVALID",
                       "only a HELD reservation may be released")
    domain.release_reservation(rec)
    return object_response(reservation_view(rec))
