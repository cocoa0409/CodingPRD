"""Logical clock control (PRD §3.9)."""
from flask import Blueprint

from db import db, base_audit_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object
from validation import get_json_body, require_str
from clock import parse_iso, to_iso_z
from services import sweep_prior_auth_expiry
from serializers import clock_state_out

bp = Blueprint("clock_route", __name__)


@bp.route("/op/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    body = get_json_body()

    to_iso8601 = require_str(body, "to_iso8601")
    try:
        parsed = parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant.")

    # Normalize to canonical ISO 8601 UTC with three fractional digits.
    db.current_utc = to_iso_z(parsed)

    cs = base_audit_fields()
    cs.update({"current_utc": db.current_utc})
    db.clock_states[cs["id"]] = cs

    # CASCADE: sweep PriorAuth deadlines (auto-EXPIRED). Supplier accreditation
    # is re-derived on read.
    sweep_prior_auth_expiry()

    return ok_object(clock_state_out(cs), 200)
