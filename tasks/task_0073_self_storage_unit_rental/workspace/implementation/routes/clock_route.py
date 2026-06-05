from flask import Blueprint

import errors
from errors import err
from db import db
from clock import parse_iso8601
from middleware import get_identity, require_role
from helpers import get_json_body
from response import success

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    body = get_json_body()
    raw = body.get("to_iso8601")
    dt = parse_iso8601(raw) if raw is not None else None
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 is required and must be ISO 8601")
    db.clock.set(dt)
    return success({}, 200)
