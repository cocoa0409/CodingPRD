"""Logical clock endpoint."""

from datetime import datetime, timezone

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.common import get_json_body, require_fields, reset_clock_seq
from services.domain import run_clock_sweeps

bp = Blueprint("clock", __name__)


@bp.route("/gifted/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("GiftedCoordinator")
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    raw = body["to_iso8601"]
    if not isinstance(raw, str):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 string", 400)
    dt = _parse_iso(raw)
    db.set_clock(dt)
    reset_clock_seq()
    run_clock_sweeps()
    return success_object({"current_utc": _format_iso(dt)}, 200)


def _parse_iso(raw):
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 timestamp", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
