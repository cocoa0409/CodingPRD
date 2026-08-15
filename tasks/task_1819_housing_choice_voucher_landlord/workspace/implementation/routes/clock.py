"""Logical-clock endpoint (test driver)."""

from datetime import datetime, timezone

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from services.clock_eval import evaluate_all

bp = Blueprint("clock", __name__)


def _parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 timestamp. Accepts trailing 'Z' or explicit offset."""
    if not isinstance(s, str):
        raise errors.invalid_amount("to_iso8601 must be a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise errors.invalid_amount("to_iso8601 must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.route("/hcv/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("HousingAuthorityAdmin")
    body = request.get_json(force=True, silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    dt = _parse_iso8601(to_iso8601)
    db.set_logical_now(dt)
    evaluate_all()
    return success_object({})
