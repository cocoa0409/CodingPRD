"""Carriers, stations, traffic rights and the logical clock."""
from flask import Blueprint

import cascades
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import authenticate
from response import ok, written, written_raw
from routes.common import READ_ROLES, list_response, read_one
from util import dt_of, fmt_dt, parse_dt

bp = Blueprint("reference", __name__)

ADMIN = ("SystemAdmin",)


# --- carriers -------------------------------------------------------------


@bp.post("/carriers")
def create_carrier():
    authenticate(ADMIN)
    payload = rv.body()
    iata = rv.req_str(payload, "iata_code", 2, 2, r"[A-Z0-9]{2}")
    icao = rv.req_str(payload, "icao_code", 3, 3, r"[A-Z]{3}")
    country = rv.req_str(payload, "country_code", 2, 2, r"[A-Z]{2}")
    is_home = rv.opt_bool(payload, "is_home_carrier", False)
    for row in store.values("carriers"):
        if row["iata_code"] == iata:
            rv.bad("A carrier with that iata_code already exists.")
        if row["icao_code"] == icao:
            rv.bad("A carrier with that icao_code already exists.")
    row = store.insert("carriers", {
        "iata_code": iata,
        "icao_code": icao,
        "country_code": country,
        "is_home_carrier": is_home,
        "status": "ACTIVE",
        "held_series_count": 0,
    })
    return written(row, 201)


@bp.get("/carriers/<carrier_id>")
def get_carrier(carrier_id):
    return ok(read_one("carriers", carrier_id))


@bp.get("/carriers")
def list_carriers():
    authenticate(READ_ROLES)
    return list_response("carriers", [
        ("country_code", rv.q_str("country_code")),
        ("status", rv.q_enum("status", "carrier_status")),
        ("is_home_carrier", rv.q_bool("is_home_carrier")),
    ])


@bp.post("/carriers/<carrier_id>/suspend")
def suspend_carrier(carrier_id):
    authenticate(ADMIN)
    carrier = store.require("carriers", carrier_id)
    payload = rv.body()
    rv.req_str(payload, "reason", 1, 500)
    if carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")
    carrier["status"] = "SUSPENDED"
    mark(carrier)
    for version in store.values("schedule_versions"):
        if version["carrier_id"] != carrier_id:
            continue
        if version["filing_status"] in ("DRAFT", "VALIDATED"):
            cascades.withdraw_version(version)
    return written(carrier)


# --- stations -------------------------------------------------------------


@bp.post("/stations")
def create_station():
    authenticate(ADMIN)
    payload = rv.body()
    iata = rv.req_str(payload, "iata_code", 3, 3, r"[A-Z]{3}")
    country = rv.req_str(payload, "country_code", 2, 2, r"[A-Z]{2}")
    level = rv.req_enum(payload, "coordination_level", "coordination_level")
    offset = rv.req_int(payload, "utc_offset_minutes", -720, 840)
    gates = rv.req_int(payload, "gate_count", 1)
    curfew_start = rv.opt_int(payload, "curfew_start_local_minutes", 0, 1439)
    curfew_end = rv.opt_int(payload, "curfew_end_local_minutes", 0, 1439)
    if (curfew_start is None) != (curfew_end is None):
        rv.bad("curfew_start_local_minutes and curfew_end_local_minutes travel together.")
    domestic = rv.opt_int(payload, "min_connect_domestic_minutes", 0, default=35)
    international = rv.opt_int(payload, "min_connect_international_minutes", 0, default=60)
    turn_override = rv.opt_int(payload, "min_turn_override_minutes", 0, default=0)
    maintenance = rv.opt_bool(payload, "maintenance_capable", False)
    for row in store.values("stations"):
        if row["iata_code"] == iata:
            rv.bad("A station with that iata_code already exists.")
    row = store.insert("stations", {
        "iata_code": iata,
        "country_code": country,
        "coordination_level": level,
        "utc_offset_minutes": offset,
        "gate_count": gates,
        "curfew_start_local_minutes": curfew_start,
        "curfew_end_local_minutes": curfew_end,
        "min_connect_domestic_minutes": domestic,
        "min_connect_international_minutes": international,
        "min_turn_override_minutes": turn_override,
        "maintenance_capable": maintenance,
    })
    return written(row, 201)


@bp.get("/stations/<station_id>")
def get_station(station_id):
    return ok(read_one("stations", station_id))


@bp.get("/stations")
def list_stations():
    authenticate(READ_ROLES)
    return list_response("stations", [
        ("country_code", rv.q_str("country_code")),
        ("coordination_level", rv.q_enum("coordination_level", "coordination_level")),
        ("maintenance_capable", rv.q_bool("maintenance_capable")),
    ])


# --- route authorities ----------------------------------------------------


@bp.post("/route-authorities")
def create_route_authority():
    authenticate(ADMIN)
    payload = rv.body()
    carrier_id = rv.req_str(payload, "carrier_id", 1)
    origin = rv.req_str(payload, "origin_country_code", 2, 2, r"[A-Z]{2}")
    dest = rv.req_str(payload, "dest_country_code", 2, 2, r"[A-Z]{2}")
    freedom = rv.req_enum(payload, "freedom_type", "freedom_type")
    cap = rv.req_int(payload, "weekly_frequency_cap", 1)
    granted_from = rv.req_dt(payload, "granted_from_utc")
    granted_until = rv.req_dt(payload, "granted_until_utc")
    if origin == dest:
        rv.bad("dest_country_code must differ from origin_country_code.")
    if dt_of(granted_until) <= dt_of(granted_from):
        rv.bad("granted_until_utc must be strictly later than granted_from_utc.")
    store.require("carriers", carrier_id)
    row = store.insert("route_authorities", {
        "carrier_id": carrier_id,
        "origin_country_code": origin,
        "dest_country_code": dest,
        "freedom_type": freedom,
        "weekly_frequency_cap": cap,
        "granted_from_utc": granted_from,
        "granted_until_utc": granted_until,
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    return written(row, 201)


@bp.get("/route-authorities/<route_authority_id>")
def get_route_authority(route_authority_id):
    return ok(read_one("route_authorities", route_authority_id))


@bp.get("/route-authorities")
def list_route_authorities():
    authenticate(READ_ROLES)
    return list_response("route_authorities", [
        ("carrier_id", rv.q_str("carrier_id")),
        ("origin_country_code", rv.q_str("origin_country_code")),
        ("dest_country_code", rv.q_str("dest_country_code")),
        ("freedom_type", rv.q_enum("freedom_type", "freedom_type")),
        ("status", rv.q_enum("status", "authority_status")),
    ])


@bp.post("/route-authorities/<route_authority_id>/suspend")
def suspend_route_authority(route_authority_id):
    authenticate(ADMIN)
    authority = store.require("route_authorities", route_authority_id)
    payload = rv.body()
    reason = rv.req_str(payload, "reason", 1, 500)
    import db as _db

    if dt_of(authority["granted_until_utc"]) < _db.now():
        authority["status"] = "EXPIRED"
    else:
        authority["status"] = "SUSPENDED"
    authority["suspension_reason"] = reason
    mark(authority)
    return written(authority)


# --- the logical clock ----------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(ADMIN)
    payload = rv.body()
    target = rv.req_dt(payload, "to_iso8601")
    store.current_utc = parse_dt(target)
    for authority in store.values("route_authorities"):
        if authority["status"] != "ACTIVE":
            continue
        if dt_of(authority["granted_until_utc"]) < store.current_utc:
            authority["status"] = "EXPIRED"
            mark(authority)
    return written_raw(lambda: {"current_utc": fmt_dt(store.current_utc)})
