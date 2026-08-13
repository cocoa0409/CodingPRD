"""Logical clock (PRD §2.5): manager-only test-driving endpoint."""

from flask import Blueprint

from db import store, fmt_dt, pub
from middleware import require_roles, body, get_dt
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("ShopManager")
    data = body()
    to = get_dt(data, "to_iso8601")
    store.clock = to
    return success({"current_utc": fmt_dt(store.clock)}, status=200)
