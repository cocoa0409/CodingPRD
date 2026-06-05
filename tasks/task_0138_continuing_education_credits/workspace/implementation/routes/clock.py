"""Logical clock control (PRD §2.11).

POST /_clock/set_current_utc still requires valid auth headers (per validation
rule priority 1) and is restricted to BoardAdmin (RBAC).
"""

from flask import Blueprint

import clock
from common import get_json_body, require_string
from middleware import require_roles
from response import success_object
from util import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("BoardAdmin")
def set_clock():
    body = get_json_body()
    to_iso8601 = require_string(body, "to_iso8601")
    dt = parse_iso(to_iso8601, field="to_iso8601")
    clock.set_now(dt)
    return success_object({}, status=200)
