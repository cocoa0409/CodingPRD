"""Logical-clock test-driving endpoint (PRD §3.9)."""
from flask import Blueprint

from response import success
from middleware import get_auth, require_role
from services import validate as V
from clock import clock, parse_iso
from errors import raise_err
import errors

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_role(role, {"PlatformOps"})
    data = V.body()
    to_iso = V.as_str(V.require(data, "to_iso8601"), "to_iso8601")
    try:
        parse_iso(to_iso)
    except (ValueError, TypeError):
        raise_err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid datetime")
    clock.set(to_iso)
    # output: null (no data)
    return success({})
