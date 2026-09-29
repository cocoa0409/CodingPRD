"""The logical clock (PRD §2.5).

This is the one endpoint exempt from the header requirements of §2.1: it may be
called with no headers at all, and any of the four roles is accepted.
"""

from flask import Blueprint

import db
import validators as v
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    data = v.body()
    raw, parsed = v.req_dt(data, "to_iso8601")
    db.set_now_utc(parsed)
    return ok({"current_utc": raw})
