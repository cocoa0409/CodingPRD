"""Test-driving logical clock (PRD 2.11)."""
from flask import Blueprint

from common import get_json_body, require_str
from db import db
from middleware import require_roles
from response import object_response
from services.timeutil import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/operations/_clock/set_current_utc", methods=["POST"])
@require_roles("FieldOps")
def set_clock():
    body = get_json_body()
    to_iso8601 = require_str(body, "to_iso8601")
    dt = parse_iso(to_iso8601, "to_iso8601")
    db.set_clock(dt)
    # output: null — return an empty data object per envelope.
    return object_response({}, 200)
