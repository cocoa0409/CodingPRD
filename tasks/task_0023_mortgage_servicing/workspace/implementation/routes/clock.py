"""POST /_clock/set_current_utc — drive simulated clock and auto-transitions."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
import response
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_INVALID_REQUEST
from middleware import KNOWN_ROLES
from services import transitions
from services.common import get_json_body, require_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Clock endpoint is the ONLY one exempt from ERR_UNAUTHENTICATED on missing headers.
    # But IF headers are provided, role must still be allowed (LoanServicer or ComplianceOfficer).
    user_role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if user_role is not None or user_id is not None:
        # If either header is present, treat as auth attempt and validate role.
        if not user_role or not user_id:
            raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header.")
        if user_role not in KNOWN_ROLES:
            raise ApiError(ERR_UNAUTHORIZED, f"Unknown role: {user_role}.")
        if user_role not in {"LoanServicer", "ComplianceOfficer"}:
            raise ApiError(ERR_UNAUTHORIZED, f"Role {user_role} not permitted for this endpoint.")

    body = get_json_body()
    iso = require_str(body, "to_iso8601")
    try:
        dt = db.parse_ts(iso)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp.")

    with db.lock:
        db.set_clock(dt)
        transitions.apply_clock_advance_transitions()

    return response.ok({"current_utc": db.fmt_ts(dt)})
