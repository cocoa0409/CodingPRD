"""Test-driving logical clock (PRD §2.4)."""

from db import current_date, iso_z, parse_date, parse_datetime, store, touch
from errors import raise_err
from flask import Blueprint
from middleware import get_ctx, require_roles
from response import success
from validation import get_body, req_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    body = get_body()
    raw = req_field(body, "to_iso8601")
    dt = parse_datetime(raw) if isinstance(raw, str) else None
    if dt is None:
        raise_err("ERR_INVALID_REQUEST", "Field to_iso8601 must be an ISO 8601 datetime")
    store.clock = dt
    # advancing past a PENDING ticket's window_date expires it
    today = current_date()
    for t in store.tickets.values():
        if t["status"] == "PENDING" and parse_date(t["window_date"]) < today:
            t["status"] = "EXPIRED"
            touch(t)
    return success({"current_utc": iso_z(store.clock)})
