"""Test-driving logical clock (PRD §2.5)."""
from flask import Blueprint

from db import store
from middleware import require_roles
from response import object_response
from services.transitions import apply_clock_transitions
from util import fmt_dt, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("RecoveryManager", "ComplianceOfficer")
    body = validate_body({
        "to_iso8601": ("datetime", True, None),
    })
    store.clock = body["to_iso8601"]
    # Advancing the clock atomically applies every due automatic transition
    # in dependency order (cure expiry, redemption expiry, assignment expiry).
    apply_clock_transitions()
    return object_response({"current_utc": fmt_dt(store.clock)})
