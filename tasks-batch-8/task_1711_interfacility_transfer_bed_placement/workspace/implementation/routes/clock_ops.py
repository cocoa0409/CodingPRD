"""POST /_clock/set_current_utc - move the logical clock (PRD 2.4).

Moving the clock eagerly rewrites nothing: lazy bed-hold expiries and
diversion effective_status re-derive from the new position on subsequent
reads and writes.  This endpoint is therefore exempt from the hold-expiry
sweep the rest of the API runs on every request.
"""

from flask import Blueprint, g

from core.clock import parse_instant, render_instant
from core.envelope import object_response
from core.errors import fail
from core.schema import body, need_str
from core.store import db

bp = Blueprint("clock_ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    b = body()
    raw = need_str(b, "to_iso8601")
    moment = parse_instant(raw)
    if moment is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.", 400)
    db.now = moment
    return object_response({"current_utc": render_instant(db.now)}, 200)
