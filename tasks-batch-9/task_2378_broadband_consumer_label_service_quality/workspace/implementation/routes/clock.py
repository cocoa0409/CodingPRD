"""The administrative logical-clock capability (PRD §2.4)."""

from flask import Blueprint

import db
import response
import validators
from middleware import authorize

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize()  # every one of the seven roles may reposition the clock
    body = validators.json_body()
    raw = validators.get_datetime(body, "to_iso8601")
    db.set_clock(db.parse_iso(raw))
    return response.success({"current_utc": db.now_iso()}, 200)
