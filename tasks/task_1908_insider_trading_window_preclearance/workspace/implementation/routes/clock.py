"""Logical clock test-driving endpoint."""
from flask import Blueprint

from db import STORE
from middleware import require_roles
from response import success
from util import Body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("LegalAdmin")
    body = Body()
    raw = body.get_str("to_iso8601")
    new_clock = body.get_dt("to_iso8601")
    body.flush()
    STORE.clock = new_clock
    return success({"current_utc": raw})
