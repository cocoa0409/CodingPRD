"""Sync events and audit logs."""
from flask import Blueprint, request, g

from db import store
from errors import raise_error, ERR_FORBIDDEN
from middleware import authenticate, enforce_tenant_isolation
from response import success, parse_pagination, paginate
from routes.tenants import get_tenant_or_404


bp = Blueprint("observability", __name__)


def _check_role(allowed):
    if g.actor_role not in allowed:
        raise_error(ERR_FORBIDDEN, "Not permitted")


@bp.route("/tenants/<tenant_id>/sync-events", methods=["GET"])
def list_sync_events(tenant_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator"))
    get_tenant_or_404(tenant_id)
    limit, offset = parse_pagination(request.args)
    target = request.args.get("target_system")
    et = request.args.get("event_type")
    items = [e for e in store.sync_events.values() if e["tenant_id"] == tenant_id]
    if target:
        items = [e for e in items if e["target_system"] == target]
    if et:
        items = [e for e in items if e["event_type"] == et]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([dict(e) for e in page], status=200,
                   pagination=meta, response_type="array")


@bp.route("/tenants/<tenant_id>/audit-logs", methods=["GET"])
def list_audit_logs(tenant_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    limit, offset = parse_pagination(request.args)
    action = request.args.get("action")
    items = [a for a in store.audit_logs.values() if a["tenant_id"] == tenant_id]
    if action:
        items = [a for a in items if a["action"] == action]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([dict(a) for a in page], status=200,
                   pagination=meta, response_type="array")
