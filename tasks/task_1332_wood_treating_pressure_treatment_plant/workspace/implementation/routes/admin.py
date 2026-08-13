"""Test-driving hooks: logical clock and charge force-state (PRD section 2.10)."""

from flask import Blueprint

from db import store, touch, public, fmt_ts
from errors import ApiError, ERR_INVALID_ENUM
from middleware import authenticate, authorize
from response import success
from util import body_json, req_field, parse_ts, resolve_charge

bp = Blueprint("admin", __name__)

CHARGE_STATUSES = {
    "STAGED", "IN_CYLINDER", "CYCLE_COMPLETE", "ASSAYED_PASS", "ASSAYED_FAIL",
    "RE_TREAT_PENDING", "TAGGED", "RELEASED", "REJECTED", "SCRAPPED",
}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = body_json()
    target = parse_ts(req_field(body, "to_iso8601"), "to_iso8601")
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    store.clock = target
    return success({"current_utc": fmt_ts(store.clock)})


@bp.route("/_charges/<chargeId>/force-state", methods=["POST"])
def force_charge_state(chargeId):
    body = body_json()
    target = req_field(body, "target_status")
    if not isinstance(target, str) or target not in CHARGE_STATUSES:
        raise ApiError(ERR_INVALID_ENUM, 400, "target_status must be a valid Charge status")
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    charge = resolve_charge(chargeId)
    charge["status"] = target
    touch(charge)
    return success(public(charge))
