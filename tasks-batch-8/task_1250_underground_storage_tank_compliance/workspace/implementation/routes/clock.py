"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

from authz import CONTRACTOR_ADMIN, require_roles
from db import store
from respond import success
from store_ops import check_closed, json_body, req_instant
from timeutil import fmt_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles([CONTRACTOR_ADMIN])
    data = json_body()
    check_closed(data, {"to_iso8601"})
    store.clock = req_instant(data, "to_iso8601")
    return success({"current_utc": fmt_dt(store.clock)})
