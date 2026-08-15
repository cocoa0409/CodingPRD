"""Logical clock admin endpoint (PlantManager only)."""

from flask import Blueprint

from db import set_clock, now, iso
from middleware import require_roles, get_json_body, req_field, as_datetime
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/pallet-ops/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlantManager")
    body = get_json_body()
    dt = as_datetime(req_field(body, "to_iso8601"), "to_iso8601")
    current = set_clock(dt)
    return success({"current_utc": iso(current)}, status=200)
