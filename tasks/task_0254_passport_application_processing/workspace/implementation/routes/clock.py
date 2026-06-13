"""Test-driving clock endpoint (anonymous-ish: requires Adjudicator role but
not entity-backed identity? PRD: clock-setting requires NO auth headers).

PRD §2.1: the two endpoints that do NOT require auth headers are applicant
registration and the test-only clock-setting capability. The RBAC matrix lists
the clock under Adjudicator exclusive ops, but the auth precondition is waived,
so we accept it without headers (and validate the body).
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from response import ok_object
from routes._helpers import get_body, require_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    if "to_iso8601" not in body or body.get("to_iso8601") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: to_iso8601")
    iso = require_str(body, "to_iso8601")
    db.clock.set(iso)
    return ok_object({"current_utc": db.clock.now_iso()}, 200)
