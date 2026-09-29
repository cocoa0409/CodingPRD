"""The logical UTC clock and its single-pass time-gated cascade (PRD 3.9)."""

from flask import Blueprint

import domain
import validation as v
from auth import guard
from envelope import empty_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    guard("POST /_clock/set_current_utc")
    body = v.body()
    raw, instant = v.req_dt(body, "current_utc")
    domain.advance_clock(instant, raw)
    return empty_response()
