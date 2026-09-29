"""The administrator-only logical clock (PRD 2.4)."""

from flask import Blueprint

from db import db, iso
from middleware import ROLE_COOP_ADMIN, require_roles
from response import object_response
from validation import json_body, read_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def set_current_utc():
    body = json_body(allowed=("to_iso8601",), required=("to_iso8601",))
    _, parsed = read_dt(body, "to_iso8601", required=True)
    db.clock = parsed
    return object_response({"current_utc": iso(parsed)})
