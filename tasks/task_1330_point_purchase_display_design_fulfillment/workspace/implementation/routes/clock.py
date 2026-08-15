"""Logical clock endpoint."""

from flask import Blueprint, request

import db
import response
from middleware import require_roles
from services.common import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/pop/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    dt = parse_iso(to_iso)
    db.set_clock(dt)
    return response.success_object({}, 200)
