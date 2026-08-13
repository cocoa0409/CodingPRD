"""Logical clock control (ComplianceOfficer only). Monotonic non-decreasing;
every advance fires the CAQH / revalidation / agreement sweeps."""
from flask import Blueprint

from db import store
from errors import ApiError, ERR_CLOCK_REGRESSION, invalid_request
from middleware import require_roles
from response import success_object
from services import run_clock_sweep
from util import fmt_ts, parse_timestamp
from validate import body

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
@require_roles("ComplianceOfficer")
def set_current_utc():
    b = body()
    raw = b.get("to_iso8601")
    dt = parse_timestamp(raw) if isinstance(raw, str) else None
    if dt is None:
        raise invalid_request("Field 'to_iso8601' is required and must be an ISO 8601 timestamp")
    if dt < store.clock:
        raise ApiError(
            ERR_CLOCK_REGRESSION,
            422,
            "The logical clock is monotonic non-decreasing",
        )
    store.clock = dt
    run_clock_sweep()
    return success_object({"current_utc": fmt_ts(store.clock)})
