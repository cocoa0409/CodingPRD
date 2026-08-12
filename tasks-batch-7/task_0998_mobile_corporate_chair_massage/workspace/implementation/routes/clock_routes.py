"""POST /chair-massage/_clock/set_current_utc — test-driving logical clock."""
from datetime import datetime, timezone

from flask import Blueprint

import db
import errors
from auth import require_roles
from clock import clock
from respond import success
from validate import json_body

bp = Blueprint("clock_routes", __name__)


def _parse_iso(value):
    if not isinstance(value, str) or not value:
        raise errors.invalid_request("Field 'to_iso8601' must be an ISO 8601 timestamp")
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise errors.invalid_request("Field 'to_iso8601' must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def license_expiry_sweep():
    """ACTIVE/SUSPENDED licenses whose expires_on has passed transition to EXPIRED."""
    today = clock.today()
    for lic in db.stores["therapist_licenses"].values():
        if lic["status"] in ("ACTIVE", "SUSPENDED") and lic["expires_on"] < today:
            lic["status"] = "EXPIRED"
            db.touch(lic)


@bp.post("/chair-massage/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = json_body()
    dt = _parse_iso(body.get("to_iso8601"))
    clock.set(dt)
    license_expiry_sweep()
    return success({"current_utc": clock.iso()}, status=200)
