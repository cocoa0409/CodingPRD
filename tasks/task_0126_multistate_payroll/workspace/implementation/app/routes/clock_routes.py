"""Clock control endpoint — test-driving the logical clock."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_PAYROLL_MANAGER, require_roles
from ..clock import clock
from ..helpers import assert_string, require_json_object
from ..responses import ok
from ..store import store

bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_roles(ROLE_PAYROLL_MANAGER)
def advance(**_kw):
    body = require_json_object()
    to_iso = assert_string(body.get("to_iso"), "to_iso")
    with store().lock:
        dt = clock.set_iso(to_iso)
        return ok({"current_iso": dt.isoformat()})
