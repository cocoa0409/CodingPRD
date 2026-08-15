"""Logical clock endpoint (PRD section 2.4)."""
from flask import Blueprint

from auth import require_roles
from db import store, format_dt
from respond import success
from validate import get_body, parse_iso_datetime, req_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ProgramAdministrator")
def set_current_utc():
    body = get_body()
    raw = req_str(body, "to_iso8601")
    store.clock = parse_iso_datetime(raw)
    return success({"current_utc": format_dt(store.clock)}, "object", 200)
