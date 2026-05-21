"""Test-driver endpoints: clock advance + sweep."""
from __future__ import annotations

from flask import Blueprint

from app.auth import require_roles
from app.envelope import success
from app.errors import ERR_VALIDATION, raise_error
from app.services.sweep import run_sweep
from app.store import STORE
from app.timeutil import CLOCK, parse_iso
from app.util import get_json_body, require_fields, require_str


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("IRSOfficer")
def advance_clock(identity):
    body = get_json_body()
    require_fields(body, ["target_timestamp"])
    target = require_str(body, "target_timestamp")
    try:
        dt = parse_iso(target)
    except ValueError:
        raise_error(ERR_VALIDATION, "target_timestamp must be ISO 8601 UTC.")
    with STORE.lock:
        CLOCK.advance_to(dt)
    return success({"now": CLOCK.now_iso()})


@bp.route("/_sweep/run", methods=["POST"])
@require_roles("IRSOfficer")
def sweep(identity):
    with STORE.lock:
        summary = run_sweep()
    return success(summary)
