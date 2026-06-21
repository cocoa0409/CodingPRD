"""Test-driving logical clock (PRD §3.1)."""
from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common
from services.policy_ops import expire_policies_if_due

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("CarrierAdmin")
def set_clock():
    body = common.get_json_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        raise errors.invalid_request("Field 'to_iso8601' is required and must be an ISO 8601 datetime.")
    try:
        new_clock = common.parse_datetime(raw)
    except Exception:
        raise errors.invalid_request("Field 'to_iso8601' must be a valid ISO 8601 datetime.")

    db.current_clock = new_clock
    # Side effect: ACTIVE policies whose trip_end_at <= clock -> EXPIRED
    expire_policies_if_due()
    return response.success_object({}, status=200)
