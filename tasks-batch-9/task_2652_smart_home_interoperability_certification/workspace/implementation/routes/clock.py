"""Logical programme clock (PRD 2.5)."""

from flask import Blueprint

import db
import middleware as M
import shape as S
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    M.auth([M.PROGRAM_ADMIN], exempt_headers=True)
    body = S.body_obj()
    instant = S.req_dt(body, "current_utc")
    db.set_clock(instant)
    return object_response({"current_utc": db.fmt_dt(instant)}, 200)
