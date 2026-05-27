"""Test-driving endpoint: POST /hoa/_clock/set_current_utc."""
from __future__ import annotations

from flask import Blueprint

import db
import recompute
from errors import raise_err
from middleware import auth_required
from response import success
from .helpers import get_json_body, require_str


bp = Blueprint("clock", __name__)


@bp.route("/hoa/_clock/set_current_utc", methods=["POST"])
@auth_required({"PlatformAdmin"})
def set_current_utc():
    body = get_json_body()
    to_s = require_str(body, "to_iso8601")
    try:
        new_clock = db.parse_iso(to_s)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST",
                  "Invalid to_iso8601 ISO 8601 string")
    db.set_current_utc(new_clock)
    recompute.clock_advance_cascade()
    return success({"current_utc": db.fmt_iso(db.get_current_utc())})
