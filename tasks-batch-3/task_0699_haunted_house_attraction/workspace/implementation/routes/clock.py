"""Logical clock control (PRD §2.5). OpsManager-only."""
from flask import Blueprint

import db
import response
from middleware import get_identity, require_role, get_json_body
from services.common import require_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    body = get_json_body()
    dt = require_datetime(body, "to_iso8601")
    db.set_clock(dt)
    return response.success({"current_utc": db.iso(dt)}, 200)
