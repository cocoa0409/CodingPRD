"""Logical clock endpoint (PlatformAdmin-only test-driving capability)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    parse_iso8601(to_iso8601, "to_iso8601")  # validates
    if not isinstance(to_iso8601, str):
        from errors import raise_err, ERR_INVALID_REQUEST

        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp string")
    db.set_current_utc(to_iso8601)
    return success_object({})
