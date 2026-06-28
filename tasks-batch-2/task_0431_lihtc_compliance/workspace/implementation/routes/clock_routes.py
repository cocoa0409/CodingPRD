"""Logical-clock endpoint (PRD §3.10)."""

from flask import Blueprint

import middleware
import response
import validate
from clock import clock

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # Headers required even for the clock endpoint; both roles allowed.
    middleware.require_role("OwnerAgent", "StateHFA")
    body = validate.get_json_body()
    to_iso = validate.as_datetime(body, "to_iso8601", required=True)
    clock.set(to_iso)
    return response.success({}, status=200)
