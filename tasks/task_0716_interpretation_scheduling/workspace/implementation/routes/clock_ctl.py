from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import ok
from helpers import get_body, require_fields
from clock import parse_iso

bp = Blueprint("clock_ctl", __name__)


@bp.post("/interpretation/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        parse_iso(body["to_iso8601"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601")
    db.clock.set(body["to_iso8601"])
    return ok({}, 200)
