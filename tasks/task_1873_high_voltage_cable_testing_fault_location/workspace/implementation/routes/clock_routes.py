from flask import Blueprint

import db
import util
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import body_dict, req_field
from middleware import authenticate
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/cable-diagnostics/_clock/set_current_utc")
def set_current_utc():
    authenticate(["SystemAdmin"])
    body = body_dict()
    raw = req_field(body, "to_iso8601")
    dt = util.parse_dt(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 datetime")
    db.set_clock(dt)
    return success({"current_utc": util.iso(dt)})
