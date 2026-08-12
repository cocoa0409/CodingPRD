"""Test-driving logical clock endpoint (PRD §2.7)."""

from flask import Blueprint

from db import clock
from errors import bad_request
from middleware import require_roles
from response import success
from services import sweep_clock
from util import get_body, parse_datetime, req_str

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc(user_id, role):
    body = get_body()
    raw = req_str(body, "to_iso8601")
    dt = parse_datetime(raw)
    if dt is None:
        raise bad_request("field to_iso8601 must be an ISO 8601 datetime")
    clock.set(dt, raw)
    sweep_clock(dt)
    return success({"current_utc": clock.raw})
