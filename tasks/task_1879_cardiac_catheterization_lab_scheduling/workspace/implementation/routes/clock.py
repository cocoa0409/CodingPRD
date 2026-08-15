"""Logical clock test-driving endpoint."""
from flask import Blueprint

from db import logical_now, set_clock
from helpers import fmt_s, get_payload, req_dt
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/cath-lab/_clock/set_current_utc", methods=["POST"])
@require_roles("CathLabScheduler")
def set_current_utc():
    data = get_payload()
    target = req_dt(data, "to_iso8601")
    set_clock(target)
    return success({"current_utc": fmt_s(logical_now())}, 200)
