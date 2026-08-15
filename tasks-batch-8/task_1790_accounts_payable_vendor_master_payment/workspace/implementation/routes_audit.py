"""Audit trail query endpoint (append-only; no update/delete endpoints exist)."""
from flask import Blueprint, request

import db
from middleware import require_auth, require_role, paginate
from response import ok_list

bp = Blueprint("audit", __name__)


@bp.route("/audit-events", methods=["GET"])
def list_audit_events():
    ctx = require_auth()
    require_role(ctx, ["VendorManager", "ComplianceOfficer", "Controller", "Auditor"])
    items = list(db.audit_events.values())
    for param in ("entity_type", "entity_id", "actor_user_id", "event_type"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e.get(param) == value]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)
