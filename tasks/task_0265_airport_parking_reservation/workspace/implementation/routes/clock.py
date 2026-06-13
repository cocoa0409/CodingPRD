"""Test-driving clock endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from middleware import get_principal, require_roles
from response import success_object
from services.reservation_ops import no_show_sweep
from services.validate import require_int, require_object, require_str
from timeutil import format_iso, parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set")
def clock_set():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin"})
    body = require_object(request.get_json(silent=True) or {})
    to_iso = require_str(body, "to_iso8601")
    store.clock = parse_iso(to_iso)
    return success_object({"current_utc": format_iso(store.clock)})


@bp.post("/_clock/advance")
def clock_advance():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin"})
    body = require_object(request.get_json(silent=True) or {})
    minutes = require_int(body, "minutes")
    base = store.current_utc()
    store.clock = base + timedelta(minutes=minutes)
    swept = no_show_sweep()
    return success_object(
        {"current_utc": format_iso(store.clock), "swept_no_show_count": swept}
    )
