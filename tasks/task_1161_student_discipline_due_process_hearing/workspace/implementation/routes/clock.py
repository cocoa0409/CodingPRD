"""Test-driving logical clock (PRD §2.4)."""
from flask import Blueprint

from db import set_clock
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import endpoint
from response import success
from util import fmt, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("DistrictAdmin")
def set_current_utc(ctx):
    target = parse_dt(ctx.body.get("to_iso8601"))
    if target is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    set_clock(target)
    return success({"current_utc": fmt(target)})
