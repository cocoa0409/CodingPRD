"""The server-held logical clock.

Every domain instant in the program is stamped from this clock, never from real
wall-clock time.  It starts at 2026-08-01T00:00:00Z on every boot.
"""

from flask import Blueprint

import db
import middleware as mw
import response

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_current_utc():
    mw.authenticate("ProgramAdmin")
    data = mw.body()
    _raw, moment = mw.req_dt(data, "to_iso8601")
    db.db.clock = moment
    return response.single({"current_utc": db.now_iso()})
