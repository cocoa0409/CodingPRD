"""Logical clock test-driving endpoint."""

from flask import Blueprint

from db import store
from middleware import require_roles, body
from response import success
from services import run_permit_expiry_sweep
from util import fmt_ts, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ContractorAdmin")
def set_current_utc():
    b = body()
    target = req_datetime(b, "to_iso8601")
    store.clock = target
    # Setting the clock fires the permit expiry sweep.
    run_permit_expiry_sweep()
    return success({"current_utc": fmt_ts(store.clock)})
