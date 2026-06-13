"""Ledger clock (test-driving) — PRD §3.15."""
from datetime import datetime, timezone
from flask import Blueprint

from db import db
from middleware import require_roles
from response import object_response
from services.validate import get_body, require_fields
import errors
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ComplianceOfficer")
def set_clock():
    body = get_body()
    require_fields(body, "to_iso8601")
    raw = body["to_iso8601"]
    try:
        cleaned = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "to_iso8601 must be an ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db.set_clock(dt)
    return object_response({}, status=200)
