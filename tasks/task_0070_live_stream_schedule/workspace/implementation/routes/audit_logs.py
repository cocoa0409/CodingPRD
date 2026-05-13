"""Audit-log query endpoint."""

from flask import Blueprint, request

import db
from middleware import require_auth, require_role, parse_pagination, paginate
from response import success


bp = Blueprint("audit_logs", __name__, url_prefix="/live-schedule/audit-logs")


@bp.get("")
def list_audit_logs():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "ComplianceReviewer"])
    limit, offset = parse_pagination()
    subject_kind = request.args.get("subject_kind")
    subject_id = request.args.get("subject_id")
    actor_role = request.args.get("actor_role")

    def predicate(log):
        if subject_kind and log.get("subject_kind") != subject_kind:
            return False
        if subject_id and log.get("subject_id") != subject_id:
            return False
        if actor_role and log.get("actor_role") != actor_role:
            return False
        return True

    items = db.list_entities("audit_logs", predicate=predicate)
    window, pagination = paginate(items, limit, offset)
    return success(window, pagination=pagination, response_type="array")
