"""POST /_clock/set_current_utc — logical clock (PRD §2.7)."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object
from services.common import normalize_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("ComplianceOfficer", "TaxDirector", "BoardDirector")
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601:
        raise errors.validation("Field 'to_iso8601' is required")
    db.current_utc = normalize_iso(to_iso8601)
    return success_object({"current_utc": db.current_utc})
