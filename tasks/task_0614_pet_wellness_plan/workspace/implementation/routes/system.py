"""System endpoints: logical clock and billing epoch (PRD §2.4, §3.9)."""
from flask import Blueprint

from db import db, parse_iso, iso
from errors import err, ERR_INVALID_REQUEST
from middleware import authenticate, require_role
from response import success, list_success
from common import get_json, require_str, public
from services.billing import run_epoch

bp = Blueprint("system", __name__)


def _clock_state():
    """The ClockState resource: id, created_at, current_utc (PRD §2.4)."""
    return {
        "id": db.clock_id,
        "created_at": db.clock_created_at,
        "current_utc": iso(db.clock),
    }


@bp.post("/wellness/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, {"BillingAdmin", "PlanAdmin"})
    body = get_json()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant")
    db.clock = dt
    return success(_clock_state())


@bp.get("/wellness/_clock")
def get_clock():
    _, role = authenticate()
    require_role(role, {"BillingAdmin", "PlanAdmin", "Member", "ClinicStaff"})
    return success(_clock_state())


@bp.post("/wellness/_billing/run-epoch")
def run_billing_epoch():
    _, role = authenticate()
    require_role(role, {"BillingAdmin"})
    created = run_epoch()
    # Returns the list of BillingCycle records created this epoch.
    limit = len(created)
    return list_success([public(c) for c in created], limit, 0, len(created))