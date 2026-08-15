"""Logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

from auth import require_roles
from envelope import raw_object_response, fmt_ts
from helpers import run_clock_sweeps
from store import store
from validate import parse_body, Struct

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("CityAdmin")
def set_current_utc():
    data, perr = parse_body()
    s = Struct(data, perr)
    to = s.get_datetime("to_iso8601")
    s.raise_if_errors()
    store.now = to
    run_clock_sweeps()
    return raw_object_response({"current_utc": fmt_ts(store.now)})
