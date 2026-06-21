"""Audit-event listing and the test-driving logical clock (PRD §2.9, §2.10)."""

from flask import Blueprint, request

import db
import clock
from errors import err, ERR_INVALID_REQUEST
from middleware import authenticate, require_role
from response import object_response, array_response
from validation import get_body, require_field, parse_pagination, sort_and_paginate

bp = Blueprint("misc", __name__)


# ---------------------------------------------------------------------------
# GET /audit-events  (ComplianceOfficer, QualityReviewer, PlatformAdmin)
# ---------------------------------------------------------------------------
@bp.route("/audit-events", methods=["GET"])
def list_audit_events():
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer", "QualityReviewer", "PlatformAdmin"})
    limit, offset = parse_pagination(request.args)
    rows = list(db.audit_events.values())
    etype = request.args.get("entity_type")
    if etype is not None:
        rows = [e for e in rows if e["entity_type"] == etype]
    eid = request.args.get("entity_id")
    if eid is not None:
        rows = [e for e in rows if e["entity_id"] == eid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc  (PlatformAdmin)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    to_iso = require_field(body, "to_iso8601")
    if not isinstance(to_iso, str):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 string.")
    try:
        clock.set_current_utc(to_iso)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp.")
    return object_response({}, 200)
