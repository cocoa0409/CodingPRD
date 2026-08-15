"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

from middleware import require_roles
from response import success_object
from services.core import sweep_expirations
from util import CLOCK, fmt_datetime, parse_datetime
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("FundAdmin")
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    # Clock advance re-runs the expiry sweeps (attestations + KYC bookkeeping).
    sweep_expirations()
    return success_object({"current_utc": fmt_datetime(CLOCK.now())})
