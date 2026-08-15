"""System / test-driving endpoints: clock and sweep."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body
from response import success_object
from services.sweep import run_sweep
from datetime import datetime, timezone

bp = Blueprint("system", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ComplianceOfficer")
def set_clock():
    body = get_json_body(required_fields=["to_iso8601"])
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a string")
    try:
        s_clean = to_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO datetime")

    db.set_clock(dt)
    return success_object({"current_utc": db.now_iso()})


@bp.route("/_admin/run-regulatory-sweep", methods=["POST"])
@require_roles("ComplianceOfficer")
def run_regulatory_sweep():
    summary = run_sweep()
    return success_object(summary)
