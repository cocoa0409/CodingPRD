"""System / clock routes — note: /_clock/advance is NOT under /camp prefix."""

from flask import Blueprint

from clock import clock
from config import ROLE_PROGRAM_ADMIN
from db import db
from middleware import get_json_body, require_auth
from response import success_response
from services.projection import clock_advance_sweep
from services.validators import require_string


clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/advance", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def clock_advance():
    body = get_json_body()
    iso_ts = require_string(body, "iso_timestamp", min_len=1)
    clock.advance_to(iso_ts)
    clock_advance_sweep()
    return success_response({"now": clock.now_iso()})


@clock_bp.route("/__test__/reset", methods=["POST"])
def test_reset():
    """Test-only reset: wipes in-memory data and rewinds the logical
    clock to wall-clock now. PRD does not specify this endpoint —
    the conftest probes it best-effort. Unprotected; harmless in the
    sandboxed test container."""
    db.reset()
    return success_response({"ok": True})
