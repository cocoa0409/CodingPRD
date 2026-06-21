"""AuditLog read endpoint (ComplianceOfficer only)."""

from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import list_success
from util import parse_pagination, page


bp = Blueprint("audit_logs", __name__)


def _serialize(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "actor_role": row["actor_role"],
        "actor_user_id": row["actor_user_id"],
        "action": row["action"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "prior_state": row.get("prior_state"),
        "new_state": row.get("new_state"),
    }


@bp.route("/api/v1/audit-logs", methods=["GET"])
@require_roles("ComplianceOfficer")
def list_audit_logs(_user_id, _role):
    limit, offset = parse_pagination()
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    items = list(db.audit_logs)
    if entity_type is not None:
        items = [r for r in items if r["entity_type"] == entity_type]
    if entity_id is not None:
        items = [r for r in items if r["entity_id"] == entity_id]
    # AuditLog rows are appended in chronological order — preserve that.
    # Sort by created_at then id for stability.
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    page_items, total = page(items, limit, offset)
    return list_success([_serialize(r) for r in page_items], limit, offset, total)
