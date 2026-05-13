from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import list_response
from services.common import (parse_pagination, serialize_audit, serialize_sync,
                              sort_by_created_at)

bp = Blueprint("audit_sync", __name__)


@bp.get("/audit-entries")
@require_roles("ProjectManager")
def list_audit():
    limit, offset = parse_pagination(request.args)
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    items = list(store.audit_entries)
    if subject_type:
        items = [e for e in items if e["subject_type"] == subject_type]
    if subject_id:
        items = [e for e in items if e["subject_id"] == subject_id]
    items = sort_by_created_at(items)
    total = len(items)
    sliced = items[offset:offset + limit]
    return list_response([serialize_audit(e) for e in sliced], total, limit, offset)


@bp.get("/external-sync-records")
@require_roles("ProjectManager")
def list_sync():
    limit, offset = parse_pagination(request.args)
    project_id = request.args.get("project_id")
    target_system = request.args.get("target_system")
    items = list(store.external_sync_records)
    if project_id:
        items = [e for e in items if e["project_id"] == project_id]
    if target_system:
        items = [e for e in items if e["target_system"] == target_system]
    items = sort_by_created_at(items)
    total = len(items)
    sliced = items[offset:offset + limit]
    return list_response([serialize_sync(e) for e in sliced], total, limit, offset)
