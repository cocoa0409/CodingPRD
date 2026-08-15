"""Test-driving logical clock endpoint."""

from flask import Blueprint

import db
import errors
import middleware
import response
import util
from services import core

bp = Blueprint("clock", __name__)


@bp.route("/conf/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    util.require_fields(body, ["to_iso8601"])
    value = body["to_iso8601"]
    dt = util.parse_dt(value)
    if dt is None:
        raise errors.validation("to_iso8601 must be a valid ISO8601 datetime")
    db.logical_clock = util.format_dt(dt)
    return response.success_object({"current_utc": db.logical_clock}, status=200)
