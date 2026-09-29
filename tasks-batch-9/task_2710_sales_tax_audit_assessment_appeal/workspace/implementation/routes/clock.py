"""Logical-clock test driver (PRD 2.6)."""
from flask import Blueprint

import db
from middleware import bad, body, guard, present
from response import empty_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@guard("AuditSupervisor")
def set_clock():
    data = body()
    if not present(data, "to_iso8601"):
        bad("to_iso8601 is required.")
    instant = db.parse_instant(data["to_iso8601"])
    if instant is None:
        bad("to_iso8601 must be an ISO 8601 instant.")
    db.set_clock(instant)
    return empty_response(200)
