from flask import Blueprint

from db import clock_now, fmt_ts, set_clock
from envelope import ok
from security import require_roles
from validators import get_body, parse_iso8601, req_str

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_current_utc():
    require_roles("ProgramAdmin")
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso)
    set_clock(dt)
    return ok({"current_utc": fmt_ts(clock_now())})
