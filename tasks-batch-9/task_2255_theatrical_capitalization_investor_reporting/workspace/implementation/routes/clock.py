"""Logical UTC clock control (PRD 2.4).

The clock reads exactly 2026-08-01T00:00:00Z at boot and never falls back to
real wall-clock time for date comparisons.
"""

from datetime import datetime, timezone

from flask import Blueprint

import db
import response
import validation as v
from errors import ERR_INVALID_REQUEST, fail
from middleware import OPERATOR_ROLES, endpoint

bp = Blueprint("clock", __name__)


def _parse_instant(text):
    raw = text.strip()
    if raw.endswith("z") or raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        fail(ERR_INVALID_REQUEST,
             "Field 'to_iso8601' is not an ISO 8601 timestamp.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@bp.post("/_clock/set_current_utc")
@endpoint(OPERATOR_ROLES)
def set_current_utc():
    data = v.body()
    text = v.req_str(data, "to_iso8601")
    db.CLOCK["now"] = _parse_instant(text)
    return response.raw_obj({"current_utc": db.iso_ts(db.logical_now())})
