"""AuditLog list endpoint."""
from flask import Blueprint, request

from db import audit_logs
from errors import err
from middleware import require_auth, get_pagination
from response import success_list
from services.projections import project_audit_log
from clock import parse_iso

bp = Blueprint("audit_logs", __name__)


@bp.route("/hotel/audit-logs", methods=["GET"])
@require_auth(roles=["PlatformAdmin", "RevenueManager"])
def list_audit_logs():
    limit, offset = get_pagination()
    event_type = request.args.get("event_type")
    subject_entity = request.args.get("subject_entity")
    subject_id = request.args.get("subject_id")
    occurred_at_from = request.args.get("occurred_at_from")
    occurred_at_to = request.args.get("occurred_at_to")

    rows = list(audit_logs.values())
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    if subject_entity:
        rows = [r for r in rows if r.get("subject_entity") == subject_entity]
    if subject_id:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    if occurred_at_from:
        try:
            d = parse_iso(occurred_at_from)
        except ValueError as e:
            raise err("ERR_INVALID_INPUT", str(e))
        rows = [r for r in rows if parse_iso(r["occurred_at"]) >= d]
    if occurred_at_to:
        try:
            d = parse_iso(occurred_at_to)
        except ValueError as e:
            raise err("ERR_INVALID_INPUT", str(e))
        rows = [r for r in rows if parse_iso(r["occurred_at"]) < d]

    rows.sort(key=lambda r: r.get("_seq", 0))
    total = len(rows)
    page = rows[offset: offset + limit]
    return success_list([project_audit_log(r) for r in page], limit, offset, total)
