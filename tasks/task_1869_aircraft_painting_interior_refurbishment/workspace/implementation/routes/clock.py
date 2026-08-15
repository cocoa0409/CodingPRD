"""Logical clock endpoint."""
from flask import Blueprint

from db import STORE, fmt_dt, set_clock
from middleware import auth
from response import success
from validation import get_body, field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth("CenterAdmin")
    data = get_body(required=True)
    to = field(data, "to_iso8601", "datetime")
    set_clock(to)
    return success({"current_utc": fmt_dt(STORE.clock)})
