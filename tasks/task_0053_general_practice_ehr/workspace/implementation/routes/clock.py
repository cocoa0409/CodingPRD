"""Test-driving logical clock endpoint (PRD §3.11)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require
from response import ok_object
from validation import get_body, require_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["FrontDesk", "QualityAnalyst", "Biller", "Provider"])
    body = get_body()
    to_iso8601 = require_str(body, "to_iso8601")
    try:
        db.clock.set_from_iso(to_iso8601)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 422, "to_iso8601 must be a valid ISO 8601 instant")
    return ok_object({"current_utc": db.clock.current_iso()}, 200)
