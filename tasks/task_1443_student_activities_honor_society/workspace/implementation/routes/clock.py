"""Logical clock test-driving endpoint."""

from flask import Blueprint

import db
from core import body, require_fields
from db import iso, parse_dt
from middleware import auth, require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth()
    require_roles(role, ("ActivitiesDirector",))
    data = body()
    require_fields(data, ["to_iso8601"])
    dt = parse_dt(data["to_iso8601"], "to_iso8601")
    db.set_clock(dt)
    return success({"current_utc": iso(dt)}, 200)
