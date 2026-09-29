"""The logical clock (PRD 2.4).  Moving it mutates no entity and fires no
deferred transition; lazy transitions materialise on the next write."""

from flask import Blueprint

import response
from db import db, parse_instant
from errors import ApiError
from guards import authorize, body, req_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize("PlatformAdmin")
    payload = body()
    raw = req_str(payload, "current_utc")
    parsed = parse_instant(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'current_utc' must be a well-formed ISO 8601 instant.")
    db.clock = parsed
    return response.ok({"current_utc": raw})
