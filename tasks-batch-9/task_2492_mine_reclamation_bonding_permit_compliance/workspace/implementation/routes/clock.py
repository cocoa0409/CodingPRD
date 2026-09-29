"""The logical clock (PRD 2.4)."""

from flask import Blueprint

import constants as C
from db import fmt_ts, set_clock
from response import object_response
from validation import authorize, datetime_field, get_body

bp = Blueprint("clock", __name__)


@bp.post("/mining/_clock/set_current_utc")
def set_current_utc():
    authorize(C.ALL_ROLES)
    body = get_body()
    value = datetime_field(body, "current_utc")
    set_clock(value)
    return object_response({"current_utc": fmt_ts(value)})
