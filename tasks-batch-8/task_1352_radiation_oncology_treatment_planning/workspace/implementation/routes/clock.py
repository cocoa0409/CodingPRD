"""Test-driving logical clock (PRD 2.8)."""
from flask import Blueprint

from db import store
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles, get_body
from response import success
from timeutil import parse_datetime, fmt_clock

bp = Blueprint("clock", __name__)


@bp.post("/oncology/_clock/set_current_utc")
@require_roles("SystemAdmin")
def set_clock(user_id):
    body = get_body()
    dt = parse_datetime(body.get("to_iso8601"))
    if dt is None:
        err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 UTC datetime")
    store.clock = dt
    return success({"current_utc": fmt_clock(store.clock)}, 200)
