"""Audit events listing."""
from flask import Blueprint, request

import db
from errors import err
from clock import parse_iso
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit", __name__)


@bp.get("/audit-events")
@require_auth(roles={"PropertyManager", "FinanceOfficer"})
def list_audit_events():
    limit, offset = get_pagination()
    subject_kind = request.args.get("subject_kind")
    subject_id = request.args.get("subject_id")
    action = request.args.get("action")
    since_raw = request.args.get("since")
    since = None
    if since_raw:
        try:
            since = parse_iso(since_raw)
        except ValueError:
            raise err("ERR_VALIDATION", "since must be ISO 8601")

    rows = list(db.audit_events.values())
    if subject_kind:
        rows = [r for r in rows if r["subject_kind"] == subject_kind]
    if subject_id:
        rows = [r for r in rows if r["subject_id"] == subject_id]
    if action:
        rows = [r for r in rows if r["action"] == action]
    if since:
        rows = [r for r in rows if parse_iso(r["occurred_at"]) >= since]
    rows.sort(key=lambda r: (r["occurred_at"], r["_seq"]))
    total = len(rows)
    page = [db.public(r) for r in rows[offset:offset + limit]]
    return success_list(page, limit=limit, offset=offset, total_count=total)
