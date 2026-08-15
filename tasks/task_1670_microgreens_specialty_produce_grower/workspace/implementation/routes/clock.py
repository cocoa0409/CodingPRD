"""Logical clock endpoint (PRD 2.5)."""
from datetime import timezone, datetime

from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import get_body, req_str, require_roles
from response import success
from services import sync_order_locks

bp = Blueprint("clock", __name__)


def _parse_iso(value):
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(400, ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
@require_roles("OpsManager")
def set_current_utc():
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    db.clock = _parse_iso(to_iso8601)
    # The clock drives the weekly order cycle: CONFIRMED <-> LOCKED.
    sync_order_locks()
    return success({}, "object", 200)
