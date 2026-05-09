"""Audit log + sync event listings."""
from flask import Blueprint, request

import db
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_sync", __name__)


@bp.route("/audit-logs", methods=["GET"])
@require_auth(roles={"Organizer", "DisciplinaryOfficer", "AppealsBoard"})
def list_audit_logs():
    limit, offset = get_pagination()
    kind = request.args.get("kind")
    subject_kind = request.args.get("subject_kind")
    subject_id = request.args.get("subject_id")
    rows = list(db.audit_logs.values())
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if subject_kind:
        rows = [r for r in rows if r["subject_kind"] == subject_kind]
    if subject_id:
        rows = [r for r in rows if r["subject_id"] == subject_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)


@bp.route("/sync-events", methods=["GET"])
@require_auth(roles={"Organizer"})
def list_sync_events():
    limit, offset = get_pagination()
    target_system = request.args.get("target_system")
    kind = request.args.get("kind")
    rows = list(db.sync_events.values())
    if target_system:
        rows = [r for r in rows if r["target_system"] == target_system]
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)
