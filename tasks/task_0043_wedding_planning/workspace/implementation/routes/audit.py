"""AuditEntry list endpoint."""
from flask import Blueprint, request, g

import db
from middleware import require_roles, check_planner_owns_project
from response import list_response, parse_pagination
from services.lookup import get_project


bp = Blueprint("audit", __name__)


@bp.get("/wedding-projects/<project_id>/audit-entries")
def list_audit(project_id):
    require_roles("Planner", "Auditor")
    p = get_project(project_id)
    if g.user_role == "Planner":
        check_planner_owns_project(p)
    limit, offset = parse_pagination(request.args)
    subject_type = request.args.get("subject_type")
    event_kind = request.args.get("event_kind")
    items = [a for a in db.audit_entries.values() if a["project_id"] == project_id]
    if subject_type:
        items = [a for a in items if a["subject_type"] == subject_type]
    if event_kind:
        items = [a for a in items if a["event_kind"] == event_kind]
    items.sort(key=lambda a: a["created_at"])
    return list_response(items, limit, offset)
