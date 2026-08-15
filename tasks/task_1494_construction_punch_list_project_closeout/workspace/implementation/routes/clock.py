"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

from authz import GCPM, require_roles
from db import store
from respond import success
from store_ops import json_body, req_temporal
from timeutil import fmt_sec

bp = Blueprint("clock", __name__, url_prefix="/closeout")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles([GCPM])
    data = json_body()
    store.clock = req_temporal(data, "to_iso8601")
    return success({"current_utc": fmt_sec(store.clock)})
