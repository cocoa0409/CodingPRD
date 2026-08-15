"""Plant logical clock endpoint (PRD §2.9)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authenticate
from response import ok_object
from routes.common import get_body, req_str
from util import parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/plant/_clock/set_current_utc")
def set_current_utc():
    authenticate(("PlantAdmin",))
    data = get_body()
    to_iso8601 = req_str(data, "to_iso8601")
    parsed = parse_dt(to_iso8601)
    if parsed is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 must be an ISO 8601 datetime string")
    db.clock["raw"] = to_iso8601
    db.clock["dt"] = parsed
    return ok_object({"current_utc": db.clock["raw"]})
