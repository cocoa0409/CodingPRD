from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import auth, require_role, require_body, ok

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    auth_uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    body = require_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or not raw:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'to_iso8601' must be an ISO 8601 string")
    try:
        dt = db.parse_ts(raw)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'to_iso8601' must be a valid ISO 8601 timestamp")
    db.set_clock(dt)
    return ok({"current_utc": db.clock_raw()}, response_type="object", status=200)
