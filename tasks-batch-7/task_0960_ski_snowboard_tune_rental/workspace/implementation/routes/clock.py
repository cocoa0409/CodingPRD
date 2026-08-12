from flask import Blueprint

from auth import auth
from envelope import success
from errors import err
from services import run_sweeps
from store import db, iso, parse_dt
from validate import body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("Manager")
    to = body().get("to_iso8601")
    if not isinstance(to, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    try:
        db.clock = parse_dt(to)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    run_sweeps()
    return success({"current_utc": iso(db.clock)})
