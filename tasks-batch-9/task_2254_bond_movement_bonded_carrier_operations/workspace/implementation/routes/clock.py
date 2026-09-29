"""The logical clock (PRD 2.4)."""
from flask import Blueprint

from db import db, iso
from errors import ApiError
from middleware import ALL_ROLES, require
from response import ok
import validate as v

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require(*ALL_ROLES)
    body = v.get_body()
    current_utc = v.req_dt(body, "current_utc")
    if current_utc < db.now:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    db.now = current_utc
    return ok({"current_utc": iso(db.now)})
