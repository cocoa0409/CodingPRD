"""Logical clock (test-driving) endpoint."""

from flask import Blueprint

import db
from middleware import auth, require_role
from response import success
from util import fmt_ts, get_body, need_dt

bp = Blueprint("clockops", __name__)


@bp.post("/soaring/_clock/set_current_utc")
def set_current_utc():
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    body = get_body()
    to = need_dt(body, "to_iso8601")
    db.CLOCK["now"] = to
    return success({"current_utc": fmt_ts(to)}, "object", 200)
