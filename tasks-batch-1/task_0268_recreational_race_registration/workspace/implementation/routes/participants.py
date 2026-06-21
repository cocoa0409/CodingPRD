"""Participant + clock endpoints."""
from flask import Blueprint, request

from db import db, new_id
from errors import err, ERR_INVALID_REQUEST
from middleware import auth, require_role, get_json, parse_iso
from response import object_response
from services.store import stamp_new, serialize_generic
from services.validate import require_str, require_enum, lookup

bp = Blueprint("participants", __name__)

GENDERS = {"M", "F", "X"}


@bp.route("/participants", methods=["POST"])
def create_participant():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    body = get_json()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    birthdate = require_str(body, "birthdate")
    gender = require_enum(body, "gender", GENDERS)

    # email must be unique across all participants (PRD 3.1)
    for p in db.participants.values():
        if p["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email must be unique across participants")

    pid = new_id()
    p = {
        "id": pid,
        "email": email,
        "full_name": full_name,
        "birthdate": birthdate,
        "gender": gender,
    }
    stamp_new(p)
    db.participants[pid] = p
    return object_response(serialize_generic(p), 201)


@bp.route("/participants/<participant_id>", methods=["GET"])
def get_participant(participant_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    p = lookup(db.participants, participant_id, "Participant")
    return object_response(serialize_generic(p), 200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    body = get_json()
    raw = body.get("to_iso8601")
    if raw is None:
        raise err(ERR_INVALID_REQUEST, "Field 'to_iso8601' is required")
    dt = parse_iso(raw)
    db.clock.set(dt)
    return object_response({}, 200)
