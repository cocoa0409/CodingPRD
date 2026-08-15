"""Logical clock test-driving endpoint."""

from flask import Blueprint

import db
from middleware import require_roles, get_json_body, check_required, check_no_unknown, parse_iso8601
from response import success_object
from services.core import evaluate_clock_transitions, now_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlantManager")
    body = get_json_body()
    check_no_unknown(body, {"to_iso8601"})
    check_required(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"], "to_iso8601")
    db.set_clock(dt)
    evaluate_clock_transitions()
    return success_object({"current_utc": now_iso()})
