"""Test-driving clock (SCAFFOLD §1.5).

Sets the server's current UTC for deterministic time-gated tests (JIT windows,
campaign windows). Not a PRD business entity; a test affordance.
"""
from flask import Blueprint

import db
from middleware import require_role, get_json_body
from response import object_response
from services.common import require_string, parse_iso8601

bp = Blueprint("clock", __name__)

ALLOWED_ROLES = {"CatalogAdmin", "AccessManager", "CampaignAdmin"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role(ALLOWED_ROLES)
    body = get_json_body()
    to_iso = require_string(body, "to_iso8601")
    dt = parse_iso8601(to_iso, "to_iso8601")
    with db.LOCK:
        db.set_clock(dt)
        return object_response({}, 200)
