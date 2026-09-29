"""The logical plant clock (PRD 2.4)."""
from flask import Blueprint

import validators as v
from db import db, fmt_dt
from middleware import ALL_ROLES, endpoint
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ALL_ROLES)
def set_current_utc():
    data = v.body()
    _raw, parsed = v.req_dt(data, "to_iso8601")
    db.now = parsed
    return ok({"current_utc": fmt_dt(parsed)})
