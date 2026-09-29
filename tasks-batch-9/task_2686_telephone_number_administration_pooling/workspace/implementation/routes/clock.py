"""The logical clock test-driving endpoint (PRD 2.5)."""

from flask import Blueprint

from db import db, fmt_instant
from middleware import ALL_ROLES, body, req_dt, require_roles
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(*ALL_ROLES)
    payload = body()
    instant = req_dt(payload, "current_utc")
    db.clock = instant
    return object_response({"current_utc": fmt_instant(db.clock)})
