"""Logical clock endpoint (test-driving). Default 2026-08-01T00:00:00Z."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import get_context, require_roles
from response import ok
from validation import parse_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    get_context()
    require_roles(["PlantManager"])
    body = parse_body({"to_iso8601": ("string", True, None)}, allow_empty=False)
    moment = db.parse_datetime(body["to_iso8601"])
    if moment is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO 8601 datetime")
    db.set_clock(moment)
    # Lazy sweeps re-evaluate on subsequent reads/references; goods-lot expiry
    # sweeps only on read endpoints (PRD §2.5), so nothing is materialized here.
    return ok({"current_utc": db.fmt_dt(moment)})
