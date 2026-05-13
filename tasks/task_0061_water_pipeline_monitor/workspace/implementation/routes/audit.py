"""Read-only audit + sync-event listings."""
from flask import Blueprint, request

from db import audit_logs, public, sync_events
from middleware import get_pagination, require_auth
from response import success_list
from services.common import get_network


bp = Blueprint("audit", __name__)


@bp.get("/networks/<network_id>/sync-events")
@require_auth(roles={"Auditor"})
def list_sync_events(network_id):
    get_network(network_id)
    target_f = request.args.get("target_system")
    event_f = request.args.get("event_type")
    limit, offset = get_pagination()
    rows = [
        e for e in sync_events.values()
        if e.get("network_id") == network_id
        and (target_f is None or e.get("target_system") == target_f)
        and (event_f is None or e.get("event_type") == event_f)
    ]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.get("/networks/<network_id>/audit-logs")
@require_auth(roles={"Auditor"})
def list_audit_logs(network_id):
    get_network(network_id)
    action_f = request.args.get("action")
    rk_f = request.args.get("resource_kind")
    limit, offset = get_pagination()
    rows = [
        a for a in audit_logs.values()
        if a.get("network_id") == network_id
        and (action_f is None or a.get("action") == action_f)
        and (rk_f is None or a.get("resource_kind") == rk_f)
    ]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)
