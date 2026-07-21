from flask import Blueprint

import errors
from errors import fail
from auth import require_auth
from store import db, parse_dt
from envelope import ok
from validation import get_body, require_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth({"TPAAdmin"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_dt(to_iso)
    except (ValueError, TypeError):
        dt = None
    if dt is None:
        fail(errors.ERR_VALIDATION, "to_iso8601 is not a valid ISO 8601 instant")
    db.clock = dt
    return ok({})
