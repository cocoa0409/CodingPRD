"""Logical clock endpoint (PRD 2.4)."""

from flask import Blueprint

from middleware import get_body, require_roles
from response import ok_object
from services.sweep import set_clock
from utils import fmt_ts, req_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("OperationsAdmin")
def set_current_utc():
    data = get_body()
    to_iso8601 = req_field(data, "to_iso8601")
    new_dt = set_clock(to_iso8601)
    return ok_object({"current_utc": fmt_ts(new_dt)})
