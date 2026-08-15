"""Logical clock test-driving endpoint (PRD 2.9)."""

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import auth_context, require_role
from response import ok
from services import domain
from util import parse_datetime
from validate import body

bp = Blueprint("clock", __name__)


@bp.route("/fof/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    data = body()
    raw = data.get("to_iso8601")
    if raw is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    target = parse_datetime(raw)
    if target is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant")
    db.STORE.clock = target
    # The sweep flips ISSUED calls whose due_date + grace has passed to
    # OVERDUE and recomputes posture for affected programs.
    domain.overdue_sweep()
    return ok({"current_utc": db.iso(db.STORE.clock)})
