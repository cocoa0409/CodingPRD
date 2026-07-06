"""Admin / test-driving endpoints: logical clock and synthetic age verification."""
from flask import Blueprint
import errors
import validate
import serialize
from db import db
from clock import clock
from middleware import require_auth
from records import touch
from response import object_response
from util import parse_datetime

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Operator only (PRD §2.5, §4).
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["to_iso8601"])
    raw = body["to_iso8601"]
    if not isinstance(raw, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a string")
    dt = parse_datetime(raw)
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant")
    clock.set(dt)
    # output: null -> empty object data (PRD §2.2)
    return object_response({}, status=200)


@bp.post("/_verify/age")
def verify_age():
    # Operator or Guide (SCAFFOLD endpoint roles).
    require_auth({"Operator", "Guide"})
    body = validate.get_json_body()
    validate.require_fields(body, ["guest_id"])
    guest_id = body["guest_id"]
    if not isinstance(guest_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "guest_id must be a string")
    guest = db.guests.get(guest_id)
    if guest is None:
        # body FK reference to a non-existent resource
        raise errors.err(errors.ERR_FK_NOT_FOUND, "guest_id references a non-existent guest")
    guest["age_verified"] = True
    touch(guest)
    return object_response(serialize.guest(guest), status=200)
