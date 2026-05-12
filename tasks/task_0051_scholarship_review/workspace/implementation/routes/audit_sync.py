"""Audit + external sync read-only endpoints."""
from flask import Blueprint, request

import db
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_sync", __name__)


@bp.route("/audit-events", methods=["GET"])
@require_auth(roles={"SchoolAdmin"})
def list_audit_events():
    limit, offset = get_pagination()
    event_type = request.args.get("event_type")
    target_entity = request.args.get("target_entity")
    target_id = request.args.get("target_id")
    rows = list(db.audit_events.values())
    if event_type:
        rows = [r for r in rows if r["event_type"] == event_type]
    if target_entity:
        rows = [r for r in rows if r["target_entity"] == target_entity]
    if target_id:
        rows = [r for r in rows if r["target_id"] == target_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total)


@bp.route("/external-sync-events", methods=["GET"])
@require_auth(roles={"SchoolAdmin"})
def list_external_sync_events():
    limit, offset = get_pagination()
    kind = request.args.get("kind")
    application_id = request.args.get("application_id")
    scholarship_id = request.args.get("scholarship_id")
    rows = list(db.external_sync_events.values())
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if application_id:
        rows = [r for r in rows if r.get("application_id") == application_id]
    if scholarship_id:
        rows = [r for r in rows if r.get("scholarship_id") == scholarship_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total)
