"""Logical clock test-driving endpoint."""

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from routes.helpers import body, require_dt_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("ProgramAdmin")
    data = body()
    dt = require_dt_field(data, "to_iso8601")
    now = db.set_clock(dt)
    return success_object({"now": db.fmt_ts(now)})
