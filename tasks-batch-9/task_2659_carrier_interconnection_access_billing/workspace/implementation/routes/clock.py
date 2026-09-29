"""The logical clock (PRD 2.5). Not mounted under /interconnection."""
from flask import Blueprint

import validation as v
from auth import PLATFORM_ADMIN, authenticate
from envelope import object_response
from errors import ApiError
from store import db, now

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate((PLATFORM_ADMIN,))
    payload = v.body()
    target = v.timestamp(payload, "target_utc")

    if target < now():
        raise ApiError("ERR_CLOCK_MUST_ADVANCE",
                       "target_utc is earlier than the current logical clock")

    db.clock = target
    return object_response({"current_utc": db.clock})
