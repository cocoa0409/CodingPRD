"""POST /_clock/set_current_utc — the test-driving logical clock."""

from flask import Blueprint

from db import set_clock, fmt_dt
from errors import err_invalid_request
from middleware import auth, require_roles, body
from response import ok
from utils import parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx = auth()
    require_roles(ctx, {"FundAdmin"})
    data = body()
    raw = data.get("to_iso8601")
    dt = parse_datetime(raw)
    if dt is None:
        raise err_invalid_request("to_iso8601 must be an ISO 8601 datetime")
    set_clock(dt)
    return ok({"current_utc": fmt_dt(dt)})
