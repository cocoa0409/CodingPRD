"""Test-driving capabilities: logical clock and sweeps."""
from flask import Blueprint

from db import store
from middleware import get_auth, require_roles
from response import success_object
from services.sweeps import run_sweeps
from util import parse_datetime, fmt_dt
from validate import get_body, validate_body

bp = Blueprint("admin", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    body = validate_body(get_body(), {"to_iso8601": ("datetime", True, None)})
    store.clock_iso = fmt_dt(parse_datetime(body["to_iso8601"]))
    return success_object({"current_utc": store.clock_iso}, 200)


@bp.post("/v1/_sweeps/run")
def sweeps_run():
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    counts = run_sweeps()
    return success_object(counts, 200)
