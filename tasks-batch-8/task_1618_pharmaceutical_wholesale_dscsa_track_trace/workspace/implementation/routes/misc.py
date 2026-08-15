"""Test-driving logical clock (PRD §2.5): POST /_clock/set_current_utc."""
from flask import Blueprint

import db
from middleware import endpoint, ALL_ROLES
from response import ok
from validation import get_body, req_datetime

bp = Blueprint("misc", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ALL_ROLES)
def set_clock():
    body = get_body()
    target = req_datetime(body, "to_iso8601")
    current = db.set_logical_clock(target)
    return ok({"current_utc": db.iso_logical(current)})
