"""AuditLog and PartnerSyncEvent list endpoints."""
from flask import Blueprint, request

import db
from middleware import auth_required
from pagination import parse_pagination, slice_sorted
from response import list_response
from views import view_audit_log, view_partner_sync_event


bp = Blueprint("audit", __name__)


@bp.get("/audit-logs")
@auth_required(["SkillAdmin"])
def list_audit_logs():
    limit, offset = parse_pagination()
    rows = list(db.audit_logs.values())
    action_type = request.args.get("action_type")
    target_entity = request.args.get("target_entity")
    target_id = request.args.get("target_id")
    if action_type:
        rows = [r for r in rows if r.get("action_type") == action_type]
    if target_entity:
        rows = [r for r in rows if r.get("target_entity") == target_entity]
    if target_id:
        rows = [r for r in rows if r.get("target_id") == target_id]
    page, total = slice_sorted(rows, limit, offset)
    return list_response([view_audit_log(r) for r in page], limit, offset, total)


@bp.get("/partner-sync-events")
@auth_required(["SkillAdmin"])
def list_sync_events():
    limit, offset = parse_pagination()
    rows = list(db.partner_sync_events.values())
    channel = request.args.get("channel")
    event_type = request.args.get("event_type")
    if channel:
        rows = [r for r in rows if r.get("channel") == channel]
    if event_type:
        rows = [r for r in rows if r.get("event_type") == event_type]
    page, total = slice_sorted(rows, limit, offset)
    return list_response([view_partner_sync_event(r) for r in page], limit, offset, total)
