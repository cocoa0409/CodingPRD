"""Logical clock test-driving endpoint (PRD 2.5)."""
from flask import Blueprint

from authz import FLEET_ADMIN, require_roles
from db import store
from respond import success
from store_ops import json_body, reject_unknown, req_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"to_iso8601"})
    store.clock = req_datetime(data, "to_iso8601")
    return success({})
