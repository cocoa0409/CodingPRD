"""Audit-event read endpoints (Auditor and AidAdministrator only).

The trail is append-only; no mutation endpoints exist.
"""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, paginate, pagination_params, require_roles
from response import success
from serializers import pub_audit_event

bp = Blueprint("audit_events", __name__)

AUDIT_ROLES = ("Auditor", "AidAdministrator")


@bp.get("/sap/audit-events/<aid>")
def get_audit_event(aid):
    authenticate()
    require_roles(*AUDIT_ROLES)
    row = store.audit_events.get(aid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "AuditEvent %s does not exist" % aid)
    return success(pub_audit_event(row))


@bp.get("/sap/audit-events")
def list_audit_events():
    authenticate()
    require_roles(*AUDIT_ROLES)
    limit, offset = pagination_params()
    rows = list(store.audit_events.values())
    student_id = request.args.get("student_id")
    if student_id is not None:
        rows = [a for a in rows if a["student_id"] == student_id]
    entity_type = request.args.get("entity_type")
    if entity_type is not None:
        rows = [a for a in rows if a["entity_type"] == entity_type]
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        rows = [a for a in rows if a["entity_id"] == entity_id]
    action = request.args.get("action")
    if action is not None:
        rows = [a for a in rows if a["action"] == action]
    page, meta = paginate(rows, limit, offset)
    return success([pub_audit_event(a) for a in page], response_type="array", pagination=meta)
