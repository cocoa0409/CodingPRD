"""Test-driving clock endpoint (PRD §2.10; scaffold §1.5 /_clock/set_current_utc).

This is the only endpoint declared outside the public business surface; it
exists so insurance validity, waitlist TTL, and check-in date eligibility
checks can be exercised deterministically.
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import get_json_body, require_auth
from response import ok_object
from services.validation import require_fields


bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_auth(["HarborMaster"])()
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    iso = body["to_iso8601"]
    try:
        dt = db.parse_iso_dt(iso)
    except (ValueError, TypeError, AttributeError):
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    canonical = db.iso_format(dt)
    with db.mutation_lock:
        db.set_current_utc(canonical)
        return ok_object({"now_utc": canonical}, 200)
