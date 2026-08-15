"""Logical-clock test-driving endpoint (PRD §2.5)."""
from datetime import datetime, timezone

from flask import Blueprint

from middleware import authorized
from response import success_object
from services.core import sweep_certificate_expiry
from util import CLOCK
from validate import get_body, req_str

bp = Blueprint("clock", __name__)


def _fmt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorized(["MobilityAdmin"])
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    # Advancing the clock past an issued certificate's coverage end sweeps
    # ISSUED -> EXPIRED with the payroll-split/record cascade (PRD §3.5).
    sweep_certificate_expiry()
    return success_object({"current_utc": _fmt(CLOCK.now())})
