"""Test-driving capabilities: clock advance and event flush."""

from flask import Blueprint, request

import db
from middleware import require_role
from response import success
from errors import raise_error, ERR_INVALID_PARAMETER
from services.package import reclaim_timeouts


bp = Blueprint("testing", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    require_role("ProjectManager")
    body = request.get_json(silent=True) or {}
    to = body.get("to")
    if not to or not isinstance(to, str):
        raise_error(ERR_INVALID_PARAMETER, "to is required (ISO 8601).")
    try:
        target = db.parse_iso(to)
    except Exception:
        raise_error(ERR_INVALID_PARAMETER, "to must be ISO 8601.")
    db.set_clock_to(target)
    reclaim_timeouts(db.now_dt())
    return success({"now": db.now_iso()})


@bp.route("/_events/dispatch-pending", methods=["POST"])
def dispatch_pending():
    require_role("ProjectManager")
    flushed = 0
    for ev in db.all_rows("external_events"):
        if ev.get("dispatch_status") == "PENDING":
            db.update("external_events", ev["id"],
                      {"dispatch_status": "DISPATCHED"}, bump=False)
            flushed += 1
    return success({"flushed": flushed})


@bp.route("/_test/reset", methods=["POST"])
def reset_state():
    """Test-only: wipe in-memory state to simulate a fresh server."""
    db.reset_all()
    return success({"reset": True})
