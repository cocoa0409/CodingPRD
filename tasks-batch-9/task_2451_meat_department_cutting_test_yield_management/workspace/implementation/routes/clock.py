"""The out-of-band logical clock control (PRD §2.4)."""

from flask import Blueprint

import middleware as mw
import validation as v
from db import db
from response import data_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    mw.authenticate((mw.STORE_ADMIN,))
    payload = v.body()
    raw, parsed = v.field_instant(payload, "current_utc", required=True)
    db.clock = parsed
    db.clock_echo = raw
    return data_response({"current_utc": raw}, 200)
