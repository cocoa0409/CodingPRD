"""Clock-advance test endpoint."""
from __future__ import annotations
from flask import Blueprint, request

from core.auth import require_roles
from core.clock import clock
from core.errors import raise_error
from core.response import success_object

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/advance")
@require_roles("PlatformAdmin")
def advance_clock():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    seconds = body.get("seconds")
    if seconds is None:
        raise_error("ERR_VALIDATION", "seconds is required.")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise_error("ERR_VALIDATION", "seconds must be a number.")
    clock.advance(float(seconds))
    return success_object({}, 200)
