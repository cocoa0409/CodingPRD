"""The injectable logical clock (PRD 2.6)."""
import auth
from flask import Blueprint
from response import object_response
from util import fmt_ts, set_now
from validation import json_body, v_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.authenticate("ProgramAdmin")
    body = json_body()
    instant = v_datetime(body, "to_iso8601")
    set_now(instant)
    return object_response({"current_utc": fmt_ts(instant)})
