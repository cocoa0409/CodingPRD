"""Logical clock endpoint."""

from flask import Blueprint

import db
from middleware import get_auth, require_roles
from response import success_object
from util import as_iso_datetime, json_body, require

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_roles(role, ("SystemAdmin",))
    body = json_body()
    to_iso8601 = as_iso_datetime(require(body, "to_iso8601"), "to_iso8601")
    db.logical_clock_iso = to_iso8601
    return success_object({"current_utc": db.logical_clock_iso})
