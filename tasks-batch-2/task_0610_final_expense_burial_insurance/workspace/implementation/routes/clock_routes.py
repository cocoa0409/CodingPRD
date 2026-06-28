"""Logical clock endpoints (PRD §2.4)."""
from flask import Blueprint

import db
from clock import set_now, parse_iso, get_now, format_iso_millis
from errors import err
from helpers import get_body
from middleware import get_identity, require_roles
from response import success
from services import policy_calc

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Underwriter", "ClaimsExaminer"})
    body = get_body()
    iso = body.get("to_iso8601")
    dt = parse_iso(iso)
    if dt is None:
        raise err("ERR_VALIDATION", "to_iso8601 is required and must be a valid ISO 8601 instant")
    with db.LOCK:
        set_now(dt)
        # Advancing the clock is a reconciling event (PRD §2.4): re-evaluate
        # every policy whose grace/lapse thresholds may now be crossed.
        for policy in list(db.policies.values()):
            if policy["coverage_status"] == "ACTIVE":
                policy_calc.reconcile_payment_dimension(policy)
    return success({}, status=200, response_type="object")


@bp.route("/_clock", methods=["GET"])
def get_clock():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Underwriter", "ClaimsExaminer", "Policyholder"})
    return success(
        {"current_utc": format_iso_millis(get_now())},
        status=200,
        response_type="object",
    )
