"""The logical UTC clock."""
from flask import Blueprint

import cascades
from core import fmt_dt, respond_object, store
from guards import Body, auth, body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(["Dispatcher", "LiftDirector", "SafetyManager", "BillingClerk", "Engineer"])
    b = Body(body())
    _raw, parsed = b.datetime("to_iso8601")
    store.now = parsed
    # Personnel certification posture, gear inspection posture and crane posture are all
    # derived against the clock on read; the crane expiry additionally runs its cascade.
    cascades.sync_clock_driven_crane_expiry()
    return respond_object({"current_utc": fmt_dt(store.now)})
