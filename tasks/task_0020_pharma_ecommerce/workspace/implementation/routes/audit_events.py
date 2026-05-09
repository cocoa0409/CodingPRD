"""Read-only listing of AuditLog and ExternalEvent."""

from __future__ import annotations

from flask import Blueprint, request

from db import db, serialize, serialize_list
from lookups import get_platform
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array

bp = Blueprint("audit_events", __name__)


@bp.get("/pharma-platforms/<pid>/audit-logs")
@require_roles("PlatformAdmin", "RegulatoryGateway")
def list_audit_logs(pid: str):
    get_platform(pid)
    rows = [r for r in db.audit_logs if r.get("platform_id") == pid]
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    action = request.args.get("action")
    if subject_type:
        rows = [r for r in rows if r.get("subject_type") == subject_type]
    if subject_id:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    if action:
        rows = [r for r in rows if r.get("action") == action]
    rows.sort(key=lambda r: r.get("_seq", 0))
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200


@bp.get("/pharma-platforms/<pid>/external-events")
@require_roles("PlatformAdmin", "RegulatoryGateway")
def list_external_events(pid: str):
    get_platform(pid)
    rows = [r for r in db.external_events if r.get("platform_id") == pid]
    channel = request.args.get("channel")
    event_type = request.args.get("event_type")
    subject_id = request.args.get("subject_id")
    if channel:
        rows = [r for r in rows if r.get("channel") == channel]
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    if subject_id:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    rows.sort(key=lambda r: r.get("_seq", 0))
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200
