"""Logical clock control (PRD 2.6)."""
from flask import Blueprint

from db import db
from middleware import ALL_ROLES, require
from response import ok
from validation import body_json, v_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require(*ALL_ROLES)
    body = body_json()
    moment = v_dt(body, "to_iso8601")
    db.clock = moment
    return ok({})
