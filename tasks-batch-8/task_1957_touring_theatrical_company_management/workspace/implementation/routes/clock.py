"""Logical clock endpoint (PRD §2.9): POST /_clock/set_current_utc.

The clock defaults to exactly 2026-08-01T00:00:00Z before any call, holds the
supplied value until the next explicit set, and never falls back to wall-clock
time. Producer-only.
"""

from flask import Blueprint

import db
from middleware import authenticate, require_roles
from response import success
from util import get_body, reject_unknown, require_present, parse_iso_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_roles(role, ("Producer",))
    body = get_body()
    reject_unknown(body, {"to_iso8601"})
    raw = require_present(body, "to_iso8601")
    dt = parse_iso_datetime(raw, "to_iso8601")
    db.logical_clock["dt"] = dt
    db.logical_clock["raw"] = raw
    return success({"current_utc": raw}, 200)
