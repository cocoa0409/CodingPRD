from flask import Blueprint

from db import db, fmt_dt
from middleware import auth, body, req_datetime
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/idp/_clock/set_current_utc")
def set_current_utc():
    auth("PlatformAdmin")
    data = body()
    instant = req_datetime(data, "to_iso8601")
    db.clock = instant
    return ok({"current_utc": fmt_dt(db.clock)})
