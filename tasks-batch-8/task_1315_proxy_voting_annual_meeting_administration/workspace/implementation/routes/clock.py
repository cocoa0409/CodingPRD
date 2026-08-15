"""Test-driving logical clock (PRD §2.4)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, require_field, parse_iso8601

bp = Blueprint("clock", __name__)


@bp.route("/proxy/_clock/set_current_utc", methods=["POST"])
@require_roles("ProxyAdministrator")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    parse_iso8601(to_iso8601, "to_iso8601")  # validates
    db.set_current_utc(to_iso8601)
    return success_object({"current_utc": db.get_current_utc()})
