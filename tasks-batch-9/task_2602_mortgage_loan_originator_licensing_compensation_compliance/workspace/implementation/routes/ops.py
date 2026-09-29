"""The test-driving surface: the logical clock and the nightly compliance
sweep (PRD 2.4, 3.9)."""
from flask import Blueprint

from db import db
from middleware import endpoint
from response import ok
from services import cascade
from util import fmt_dt
from validators import Body, raw_body

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("PlatformAdmin")
def set_clock():
    body = Body(raw_body())
    to_iso8601 = body.datetime("to_iso8601")
    # No entity is mutated; subsequent requests simply observe the new instant.
    db.clock = to_iso8601
    return ok({"current_utc": fmt_dt(db.clock)})


@bp.route("/_ops/daily-license-sweep", methods=["POST"])
@endpoint("PlatformAdmin")
def daily_license_sweep():
    result = cascade.daily_license_sweep()
    result["swept_at"] = fmt_dt(result["swept_at"])
    return ok(result)
