"""Test-driving logical clock endpoint (PRD section 2.5)."""
from flask import Blueprint

from db import set_clock
from middleware import require_roles, get_body
from response import obj_response
from util import req, check_unknown, fmt_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("FaireOperator")
    body = get_body()
    check_unknown(body, {"to_iso8601"})
    instant = req(body, "to_iso8601", "dt")
    set_clock(instant)
    return obj_response({"current_utc": fmt_dt(instant)})
