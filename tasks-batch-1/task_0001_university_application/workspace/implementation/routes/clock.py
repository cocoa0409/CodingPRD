"""System clock endpoints (test-driving)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import auth_required
from response import ok_object
from routes._helpers import get_body, require_fields

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Anonymous per scaffold §1.4 priority 1 ("all except POST /applicants and
    # POST /_clock/set_current_utc"). PRD §2.1.1 confirms: skips auth-header
    # requirement.
    auth_required({"PlatformAdmin", "Anonymous"}, allow_anonymous=True)()
    body = get_body()
    require_fields(body, ["to_iso8601"])
    v = body["to_iso8601"]
    if not isinstance(v, str) or not v:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be non-empty string")
    db.system_clock["current_utc"] = v
    return ok_object(db.system_clock)


@bp.get("/_clock")
def read_clock():
    auth_required({"PlatformAdmin", "Applicant", "AdmissionsOfficer", "FinancialAidOfficer"})()
    return ok_object(db.system_clock)
