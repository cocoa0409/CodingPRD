"""Deterministic clock control (PRD §3.9)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import get_identity, require_role
from response import success
from services import reservation_sm as sm
from services.util import get_body, parse_datetime, as_int

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set")
def clock_set():
    _, role = get_identity()
    require_role(role, {"CenterManager", "FrontDesk"})
    body = get_body()
    if "now_utc" not in body or body["now_utc"] is None:
        raise err("ERR_INVALID_REQUEST", "now_utc is required")
    dt = parse_datetime(body["now_utc"], "now_utc")
    db.set_clock(dt)
    return success({})


@bp.post("/_clock/advance")
def clock_advance():
    _, role = get_identity()
    require_role(role, {"CenterManager", "FrontDesk"})
    body = get_body()
    minutes = as_int(body, "minutes", minimum=0)
    db.advance_clock(minutes)
    # Fire the hold-TTL expiry sweep (PRD §3.9).
    sm.hold_ttl_sweep()
    return success({})
