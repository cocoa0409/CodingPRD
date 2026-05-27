"""SystemClock test-driving endpoints."""

from flask import Blueprint

from db import db, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success
from util import get_json_body, require_fields


bp = Blueprint("system_clock", __name__)


def _serialize(state):
    return {
        "id": state["id"],
        "created_at": state["created_at"],
        "current_utc": state["current_utc"],
    }


@bp.route("/api/v1/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock(_user_id, _role):
    body = get_json_body()
    require_fields(body, "to_iso8601")
    iso = body["to_iso8601"]
    if not isinstance(iso, str):
        raise_api("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 string")
    try:
        parse_iso(iso)
    except Exception:
        raise_api("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 string")
    state = db.clock_set(iso)
    return success(_serialize(state))


@bp.route("/api/v1/_clock", methods=["GET"])
@require_roles("PlatformAdmin", "Recruiter", "ComplianceOfficer")
def get_clock(_user_id, _role):
    state = db.clock_get()
    return success(_serialize(state))
