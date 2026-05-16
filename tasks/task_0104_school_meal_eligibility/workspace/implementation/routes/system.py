"""System endpoints: /_clock/advance and /__test__/reset."""

from datetime import datetime, timezone
from flask import Blueprint, request

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, lock, now_iso
from core.validation import require_body, require_field, parse_iso8601


bp = Blueprint("system", __name__)


@bp.post("/__test__/reset")
def test_reset():
    """Test-harness only. Wipes all in-memory state and resets the clock to a
    fixed instant. Auth is bypassed for this endpoint."""
    with lock():
        STORE.reset()
        CLOCK.set_to(datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    return success_object({})


@bp.post("/_clock/advance")
@require_roles("AuditOfficer")
def advance_clock():
    body = require_body(request)
    target_raw = require_field(body, "target_instant", kind="string")
    target = parse_iso8601(target_raw, "target_instant")
    with lock():
        ok = CLOCK.advance_to(target)
        if not ok:
            raise_error("ERR_VALIDATION",
                        "target_instant must be strictly greater than current server now")
    return success_object({"now": CLOCK.now_iso()})
