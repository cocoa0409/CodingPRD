from flask import Blueprint

from db import db, parse_dt, fmt_dt
from middleware import require_auth
from response import success
from helpers import get_json_body, as_str
from errors import err

bp = Blueprint("clock", __name__)


@bp.post("/refractive/_clock/set_current_utc")
@require_auth(["Coordinator"])
def set_clock():
    body = get_json_body()
    to_iso = as_str(body, "to_iso8601")
    try:
        dt = parse_dt(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    db.set_clock(dt)
    return success({"current_utc": fmt_dt(db.now())}, 200)
