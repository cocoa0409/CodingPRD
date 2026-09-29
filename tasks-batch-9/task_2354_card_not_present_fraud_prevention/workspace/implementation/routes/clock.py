"""The logical-clock harness (PRD 2.4)."""

from flask import Blueprint

from db import db
from errors import ApiError
from middleware import roles
from response import ok
import validators as v

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@roles("PlatformAdmin")
def set_current_utc():
    payload = v.body()
    # priority 20: current_utc must be a valid ISO-8601 UTC instant
    moment = v.as_datetime(payload, "current_utc")
    # priority 74: the clock never moves backwards
    if moment < db.current_utc:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    db.current_utc = moment
    # No entity is written; the response echoes the new reading.
    return ok({"current_utc": moment})
