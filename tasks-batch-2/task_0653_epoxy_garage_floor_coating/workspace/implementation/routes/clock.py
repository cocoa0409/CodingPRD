"""Logical clock (SCAFFOLD §1.5 / PRD §2.5)."""
from flask import Blueprint

from db import db
from middleware import authenticate, require_role
from response import success
from services.common import get_body
from services.timeutil import parse_iso8601

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    target = parse_iso8601(body.get("to_iso8601"), "to_iso8601")
    db.set_clock(target)
    return success({}, 200)
