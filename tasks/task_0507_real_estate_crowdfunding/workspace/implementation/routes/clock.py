"""Logical clock control (PRD §2.9)."""
from datetime import datetime, timezone

from flask import Blueprint

import db
from errors import err
from middleware import require_role
from response import success
from services import validate as V

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role({"Operator", "FundManager"})
    body = V.get_body()
    to_iso = V.req_str(body, "to_iso8601")
    raw = to_iso.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    db.set_clock(dt)
    return success({})
