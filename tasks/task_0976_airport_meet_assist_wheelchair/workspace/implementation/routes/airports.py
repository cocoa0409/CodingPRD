"""Airports, terminals, flight segments."""
from datetime import datetime, timezone

from flask import Blueprint

import db
from errors import bad_request, invalid_state, not_found
from middleware import require_roles
from response import success_object
from routes.util import (IATA_RE, get_or_404, json_body, list_response,
                         parse_datetime_field, require_enum, require_fields,
                         serialize_airport, serialize_leg, serialize_segment,
                         serialize_terminal)
from services import cascades

bp = Blueprint("airports", __name__)

ALL_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "Agent",
             "Confirmer", "Requester", "BillingClerk")


# ---------------------------------------------------------------------------
# Airports
# ---------------------------------------------------------------------------

@bp.post("/maa/airports")
def create_airport():
    require_roles("PlatformAdmin")
    body = json_body()
    require_fields(body, ["iata_code", "tz_offset_minutes", "meet_buffer_minutes"])
    iata = body["iata_code"]
    if not isinstance(iata, str) or not IATA_RE.match(iata):
        raise bad_request("iata_code must match ^[A-Z]{3}$")
    for existing in db.airports.values():
        if existing["iata_code"] == iata:
            raise bad_request("iata_code must be globally unique")
    tz = body["tz_offset_minutes"]
    if not isinstance(tz, int) or isinstance(tz, bool):
        raise bad_request("tz_offset_minutes must be an integer")
    mbm = body["meet_buffer_minutes"]
    if not isinstance(mbm, int) or isinstance(mbm, bool) or mbm < 15:
        raise bad_request("meet_buffer_minutes must be >= 15")
    airport = db.common_fields()
    airport.update({
        "iata_code": iata,
        "tz_offset_minutes": tz,
        "meet_buffer_minutes": mbm,
        "posture": "NORMAL",
        "ops_epoch": 0,
    })
    db.airports[airport["id"]] = airport
    return success_object(serialize_airport(airport), status=201)


@bp.get("/maa/airports/<aid>")
def get_airport(aid):
    require_roles(*ALL_ROLES)
    airport = get_or_404(db.airports, aid, "Airport")
    return success_object(serialize_airport(airport))


@bp.post("/maa/airports/<aid>/posture")
def change_posture(aid):
    require_roles("OpsManager")
    airport = get_or_404(db.airports, aid, "Airport")
    body = json_body()
    require_fields(body, ["posture"])
    new_posture = require_enum(body["posture"], {"NORMAL", "DEGRADED", "LOCKDOWN"}, "posture")
    ladder = {
        "NORMAL": {"DEGRADED"},
        "DEGRADED": {"LOCKDOWN", "NORMAL"},
        "LOCKDOWN": {"NORMAL"},
    }
    if new_posture == airport["posture"]:
        raise invalid_state(f"Airport already in posture {new_posture}")
    if new_posture not in ladder.get(airport["posture"], set()):
        raise invalid_state(
            f"Cannot transition posture from {airport['posture']} to {new_posture}")
    cascades.apply_posture_change(airport, new_posture)
    return success_object(serialize_airport(airport))


@bp.post("/maa/airports/<aid>/run_ops")
def run_ops(aid):
    require_roles("OpsManager")
    airport = get_or_404(db.airports, aid, "Airport")
    cascades.run_ops_epoch(airport)
    return success_object(serialize_airport(airport))


# ---------------------------------------------------------------------------
# Terminals
# ---------------------------------------------------------------------------

@bp.post("/maa/airports/<aid>/terminals")
def create_terminal(aid):
    require_roles("PlatformAdmin")
    airport = get_or_404(db.airports, aid, "Airport")
    body = json_body()
    require_fields(body, ["code", "requires_secure_escort"])
    code = body["code"]
    if not isinstance(code, str) or not code.strip():
        raise bad_request("code must be a non-empty string")
    for t in db.terminals.values():
        if t["airport_id"] == airport["id"] and t["code"] == code:
            raise bad_request("code must be unique within the airport")
    rse = body["requires_secure_escort"]
    if not isinstance(rse, bool):
        raise bad_request("requires_secure_escort must be a boolean")
    terminal = db.common_fields()
    terminal.update({
        "airport_id": airport["id"],
        "code": code,
        "requires_secure_escort": rse,
        "status": "OPEN",
    })
    db.terminals[terminal["id"]] = terminal
    return success_object(serialize_terminal(terminal), status=201)


@bp.get("/maa/airports/<aid>/terminals")
def list_terminals(aid):
    require_roles(*ALL_ROLES)
    airport = get_or_404(db.airports, aid, "Airport")
    items = [t for t in db.terminals.values() if t["airport_id"] == airport["id"]]
    return list_response(items, serialize_terminal)


@bp.get("/maa/terminals/<tid>")
def get_terminal(tid):
    require_roles(*ALL_ROLES)
    terminal = get_or_404(db.terminals, tid, "Terminal")
    return success_object(serialize_terminal(terminal))


@bp.get("/maa/terminals/<tid>/segments")
def list_terminal_segments(tid):
    require_roles(*ALL_ROLES)
    terminal = get_or_404(db.terminals, tid, "Terminal")
    items = [s for s in db.segments.values() if s["terminal_id"] == terminal["id"]]
    return list_response(items, serialize_segment)


# ---------------------------------------------------------------------------
# Flight Segments
# ---------------------------------------------------------------------------

@bp.post("/maa/airports/<aid>/segments")
def create_segment(aid):
    require_roles("PlatformAdmin")
    airport = get_or_404(db.airports, aid, "Airport")
    body = json_body()
    require_fields(body, ["flight_no", "direction", "terminal_id", "scheduled_utc"])
    flight_no = body["flight_no"]
    if not isinstance(flight_no, str) or not flight_no.strip():
        raise bad_request("flight_no must be a non-empty string")
    direction = require_enum(body["direction"], {"ARRIVAL", "DEPARTURE"}, "direction")
    terminal = db.terminals.get(body["terminal_id"])
    if terminal is None:
        raise bad_request("terminal_id does not resolve")
    if terminal["airport_id"] != airport["id"]:
        raise bad_request("terminal_id belongs to another airport")
    scheduled_utc = parse_datetime_field(body["scheduled_utc"], "scheduled_utc")
    segment = db.common_fields()
    segment.update({
        "airport_id": airport["id"],
        "flight_no": flight_no,
        "direction": direction,
        "terminal_id": terminal["id"],
        "scheduled_utc": scheduled_utc,
        "actual_utc": None,
        "status": "SCHEDULED",
        "international": bool(body.get("international", False)),
    })
    db.segments[segment["id"]] = segment
    return success_object(serialize_segment(segment), status=201)


@bp.get("/maa/airports/<aid>/segments")
def list_segments(aid):
    require_roles(*ALL_ROLES)
    airport = get_or_404(db.airports, aid, "Airport")
    items = [s for s in db.segments.values() if s["airport_id"] == airport["id"]]
    direction = None
    status = None
    terminal_id = None
    from flask import request as _req
    direction = _req.args.get("direction")
    status = _req.args.get("status")
    terminal_id = _req.args.get("terminal_id")
    if direction:
        items = [s for s in items if s["direction"] == direction]
    if status:
        items = [s for s in items if s["status"] == status]
    if terminal_id:
        items = [s for s in items if s["terminal_id"] == terminal_id]
    return list_response(items, serialize_segment)


@bp.get("/maa/segments/<sid>")
def get_segment(sid):
    require_roles(*ALL_ROLES)
    segment = get_or_404(db.segments, sid, "FlightSegment")
    return success_object(serialize_segment(segment))


@bp.get("/maa/segments/<sid>/legs")
def list_segment_legs(sid):
    require_roles(*ALL_ROLES)
    segment = get_or_404(db.segments, sid, "FlightSegment")
    items = [l for l in db.legs.values() if l["segment_id"] == segment["id"]]
    return list_response(items, serialize_leg)


@bp.post("/maa/segments/<sid>/events")
def segment_event(sid):
    require_roles("OpsManager")
    segment = get_or_404(db.segments, sid, "FlightSegment")
    body = json_body()
    require_fields(body, ["event_type"])
    event_type = require_enum(body["event_type"], {"LANDED", "DEPARTED", "CANCELLED"}, "event_type")
    if event_type in {"LANDED", "DEPARTED"}:
        if segment["status"] != "SCHEDULED":
            raise invalid_state(f"Segment is {segment['status']}")
        actual = body.get("actual_utc")
        if actual is None:
            raise bad_request("actual_utc is required for LANDED/DEPARTED")
        segment["actual_utc"] = parse_datetime_field(actual, "actual_utc")
        segment["status"] = "LANDED" if event_type == "LANDED" else "DEPARTED"
        db.touch(segment)
    else:  # CANCELLED
        if segment["status"] == "CANCELLED":
            raise invalid_state("Segment already CANCELLED")
        segment["status"] = "CANCELLED"
        db.touch(segment)
        # Cascade: any PLANNED leg referencing this segment -> CANCELLED
        for leg in list(db.legs.values()):
            if leg["segment_id"] == segment["id"] and leg["status"] == "PLANNED":
                leg["status"] = "CANCELLED"
                db.touch(leg)
    return success_object(serialize_segment(segment))
