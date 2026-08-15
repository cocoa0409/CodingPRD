"""Logical clock endpoint (PRD 2.5)."""
import db
from auth import require
from envelope import success_object
from validate import get_body, req_datetime, parse_datetime_value

from . import bp


@bp.post("/network/_clock/set_current_utc")
def set_current_utc():
    require({"NetworkOps"})
    body = get_body()
    raw = req_datetime(body, "to_iso8601")
    dt = parse_datetime_value("to_iso8601", raw)
    db.set_clock(dt, raw)
    return success_object({"current_utc": db.clock_str}, 200)
