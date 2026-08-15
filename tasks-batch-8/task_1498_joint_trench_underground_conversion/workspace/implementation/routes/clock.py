"""Test-driving logical clock endpoint (ProgramManager only).

Sets the server-side logical clock to the supplied instant and runs the lazy
permit-expiry sweep. The server never falls back to wall-clock time.
"""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services import domain
from util import get_json_body, require_ts

bp = Blueprint("clock", __name__, url_prefix="/api/_clock")


@bp.route("/set_current_utc", methods=["POST"])
@require_roles("ProgramManager")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    value = require_ts(body, "to_iso8601")
    db.set_clock_raw(value)
    domain.sweep_permits()  # lazy ISSUED -> EXPIRED flips on clock advance
    return success_object({})
