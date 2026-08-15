"""Platform endpoints: the test-driving logical clock (PRD §2.5)."""
from flask import Blueprint

import db
from db import store
from middleware import authenticate, require_roles
from response import ok
from services import ACTIVE_TURN_STATUSES, sync_turn
from validation import get_body, parse_iso_datetime, validate_schema
from errors import ApiError

bp = Blueprint("misc", __name__)


@bp.post("/make-ready/_clock/set_current_utc")
def set_current_utc():
    authenticate()
    require_roles(["PlatformAdmin"])
    body = get_body()
    validate_schema(body, {"to_iso8601": ("datetime", True, None)})
    dt = parse_iso_datetime(body["to_iso8601"])
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_iso8601 must be an ISO 8601 datetime")
    db.set_logical_clock(dt)
    # Setting the clock re-triggers projection recomputation on every
    # non-terminal, scoped-or-later turn, with commitment risk re-evaluated.
    for turn in store.turns.values():
        if turn["status"] in ACTIVE_TURN_STATUSES:
            sync_turn(turn)
    return ok({})
