"""Test-driving logical clock endpoint (PRD §2.10)."""
from flask import Blueprint

import db
import response
from middleware import require_roles
from services import common

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = common.get_body()
    to_iso = common.require_field(body, "to_iso8601")
    dt = common.parse_iso(to_iso, "to_iso8601")
    db.clock.set(dt)
    return response.success({"current_utc": db.iso_now()}, 200)
