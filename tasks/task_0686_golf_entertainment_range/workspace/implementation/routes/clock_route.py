"""Logical-clock test-driving endpoint (PRD §2.9; SCAFFOLD §1.5)."""

from flask import Blueprint

from response import success
from middleware import get_caller, require_roles
from errors import raise_err, ERR_INVALID_REQUEST
from services import validate as V
from clock import clock, parse_iso

bp = Blueprint("clock_route", __name__)


@bp.post("/golf/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    require_roles(caller, {"RangeManager"})
    data = V.body()
    to_iso = V.as_str(V.require(data, "to_iso8601"), "to_iso8601")
    try:
        parse_iso(to_iso)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    clock.set_from_iso(to_iso)
    # output: null (no data)
    return success({})
