"""Logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

from db import store
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import ok
from services import advance_clock
from util import fmt_dt, get_body, req_present, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("OwnerEngineer")
def set_current_utc():
    body = get_body()
    to_dt = parse_dt(req_present(body, "to_iso8601"), "to_iso8601")
    # Monotonic: never backwards.
    if to_dt < store.logical_now:
        raise ApiError(ERR_INVALID_REQUEST, "The logical clock cannot move backwards", 400)
    advance_clock(to_dt)
    return ok({"current_utc": fmt_dt(store.logical_now)})
