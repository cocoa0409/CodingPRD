"""POST /_clock/set_current_utc - the deterministic logical clock (section 2.4)."""

from flask import Blueprint

import clock
import response
import validate
from auth import endpoint

bp = Blueprint("clock_control", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("ProgramAdmin", "VerificationAnalyst", "AppealReviewer", "RecoveryAgent")
def set_current_utc():
    payload = validate.body()
    raw = payload.get("to_iso8601")
    if raw is None:
        validate.bad("to_iso8601 is required.")
    if not isinstance(raw, str):
        validate.bad("to_iso8601 must be an ISO 8601 instant string.")
    instant = clock.parse_datetime(raw)
    if instant is None:
        validate.bad("to_iso8601 must be an ISO 8601 instant string.")
    clock.set_now(instant)
    return response.raw_out({"current_utc": clock.fmt_dt(clock.now())}, 200)
