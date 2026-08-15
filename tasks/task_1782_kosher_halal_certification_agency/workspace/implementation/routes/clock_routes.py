"""Logical clock endpoint (AgencyAdmin only): set the current UTC instant and
run the deterministic five-step sweep."""
from flask import Blueprint

from db import iso_logical, set_logical_now
from middleware import require_roles
from response import ok
from services.sweep import run_sweep
from validation import body_json, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    data = body_json()
    to_instant = req_datetime(data, "to_iso8601")
    require_roles("AgencyAdmin")
    set_logical_now(to_instant)
    run_sweep(to_instant)
    return ok({"current_utc": iso_logical(to_instant)})
