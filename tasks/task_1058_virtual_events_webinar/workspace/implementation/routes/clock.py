"""The logical clock (PRD 2.5)."""

from flask import Blueprint

import db
from auth import authorize
from db import S
from response import ok
from validate import body, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize("PlatformAdmin")
    b = body()
    instant = req_dt(b, "to_iso8601")
    S.clock = instant
    return ok({"current_utc": db.fmt_dt(S.clock)})
