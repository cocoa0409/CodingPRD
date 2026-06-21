"""Test-driving clock control (PRD §3.4 / §4)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services.tour_engine import parse_dt
from validate import parse_body, check_str_type

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin"])
    body = parse_body()
    to_iso = check_str_type(body, "to_iso8601", required=True)
    dt = parse_dt(to_iso)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601")
    db.set_clock(dt)
    return success({}, status=200)
