"""Logical clock test-driving endpoint (PRD 2.11)."""
from flask import Blueprint

from authz import PLATFORM_ADMIN, require_roles
from db import store
from respond import success
from store_ops import json_body, req_temporal
from timeutil import as_instant, fmt_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles([PLATFORM_ADMIN])
    data = json_body()
    to = req_temporal(data, "to_iso8601")
    store.clock = as_instant(to)
    return success({"current_utc": fmt_dt(store.clock)})
