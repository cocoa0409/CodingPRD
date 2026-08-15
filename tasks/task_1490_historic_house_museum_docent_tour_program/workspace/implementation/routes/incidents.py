"""Safety incident endpoints and the closure cascade."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok
from services import (
    fire_critical_cascade,
    lookup,
    resolve_incident_side_effects,
    ser_incident,
    stamp,
    touch,
)
from util import body, req_enum, req_str

bp = Blueprint("incidents", __name__)

SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")


@bp.post("/safety-incidents")
def create_incident():
    auth(["MuseumAdmin", "Curator", "FrontDeskStaff", "Docent"])
    data = body()
    # Tier 3 (existence): body FKs room_id, slot_id.
    raw_room = data.get("room_id")
    room = lookup("rooms", raw_room) if raw_room is not None else None
    raw_slot = data.get("slot_id")
    if raw_slot is not None:
        lookup("slots", raw_slot)
    # Tier 4 (request shape).
    if room is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: room_id")
    if raw_slot is not None and not isinstance(raw_slot, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "slot_id must be a string")
    severity = req_enum(data, "severity", SEVERITIES)
    description = req_str(data, "description")
    rec = {
        "id": new_id(),
        "room_id": room["id"],
        "slot_id": raw_slot,
        "severity": severity,
        "description": description,
        "status": "REPORTED",
    }
    stamp(rec)
    DB["incidents"][rec["id"]] = rec
    if severity == "CRITICAL":
        fire_critical_cascade(room)
    return ok(ser_incident(rec), 201)


@bp.post("/safety-incidents/<iid>/resolve")
def resolve_incident(iid):
    auth(["MuseumAdmin", "Curator"])
    incident = lookup("incidents", iid)
    if incident["status"] != "REPORTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a REPORTED incident can be resolved"
        )
    incident["status"] = "RESOLVED"
    touch(incident)
    resolve_incident_side_effects(incident)
    return ok(ser_incident(incident))
