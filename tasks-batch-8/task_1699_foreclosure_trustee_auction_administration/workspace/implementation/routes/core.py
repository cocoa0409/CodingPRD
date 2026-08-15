"""Logical clock + Beneficiary routes."""
from flask import Blueprint

import db
from db import stamp_new, touch, _format_iso
from errors import err_invalid_request
from middleware import require_roles
from response import success_object
from services.domain import get_beneficiary, view
from services.validate import get_body, check_unknown, req_string

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock (test-driving; TrusteeAdmin only). Startup default is exactly
# 2026-08-01T00:00:00Z; advancing fires no automatic sweeps — quote and claim
# expiry are derived lazily (PRD §2.5).
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"], strict_slashes=False)
@require_roles("TrusteeAdmin")
def set_clock(user_id, role):
    body = get_body()
    check_unknown(body, {"to_iso8601"})
    target = body.get("to_iso8601")
    if not isinstance(target, str):
        raise err_invalid_request("missing or invalid field: to_iso8601")
    try:
        new_now = db.CLOCK.set(target)
    except Exception:
        raise err_invalid_request("invalid ISO8601 datetime: to_iso8601")
    return success_object({"current_utc": _format_iso(new_now)}, status=200)


# ---------------------------------------------------------------------------
# Beneficiary
# ---------------------------------------------------------------------------

@bp.route("/api/beneficiaries", methods=["POST"], strict_slashes=False)
@require_roles("TrusteeAdmin")
def create_beneficiary(user_id, role):
    body = get_body()
    check_unknown(body, {"name", "reference_code", "contact_email"})
    name = req_string(body, "name")
    reference_code = req_string(body, "reference_code")
    contact_email = req_string(body, "contact_email")
    if any(b["reference_code"] == reference_code for b in db.beneficiaries.values()):
        raise err_invalid_request("reference_code must be unique across all beneficiaries")
    ben = {
        "name": name,
        "reference_code": reference_code,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "total_outstanding_advances_cents": 0,
    }
    stamp_new(ben)
    db.beneficiaries[ben["id"]] = ben
    return success_object(view(ben), status=201)


@bp.route("/api/beneficiaries/<beneficiary_id>", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager")
def read_beneficiary(user_id, role, beneficiary_id):
    return success_object(view(get_beneficiary(beneficiary_id)))


@bp.route("/api/beneficiaries/<beneficiary_id>/suspend", methods=["POST"], strict_slashes=False)
@require_roles("TrusteeAdmin")
def suspend_beneficiary(user_id, role, beneficiary_id):
    body = get_body()
    check_unknown(body, set())
    ben = get_beneficiary(beneficiary_id)
    if ben["status"] != "ACTIVE":
        # one-way transition; no dedicated catalog error for re-suspension
        raise err_invalid_request("beneficiary is not ACTIVE")
    ben["status"] = "SUSPENDED"
    touch(ben)
    return success_object(view(ben))
