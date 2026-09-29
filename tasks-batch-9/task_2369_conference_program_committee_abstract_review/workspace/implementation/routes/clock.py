"""Test-driving endpoint: the logical clock (PRD 2.4)."""

from flask import Blueprint

from db import db
from middleware import ROLE_ADMIN, endpoint
from response import ok
from validators import body_json, v_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ROLE_ADMIN)
def set_current_utc(actor):
    body = body_json()
    current_utc = v_datetime(body, "current_utc", required=True)
    db.set_clock(current_utc)
    return ok({"current_utc": db.now_raw()})
