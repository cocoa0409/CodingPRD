"""Audit log listing."""
from flask import Blueprint, request

from .. import store
from ..auth import require_auth
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success


bp = Blueprint("audit_logs", __name__)


@bp.get("/audit-logs")
@require_auth(["PlatformAdmin"])
def list_audit_logs():
    limit, offset = get_pagination()
    rows = store.list_all("AuditLog")
    for k in ("actor_user_id", "action", "target_entity_type", "target_entity_id"):
        v = request.args.get(k)
        if v:
            rows = [r for r in rows if r.get(k) == v]
    frm = request.args.get("from")
    to = request.args.get("to")
    if frm:
        rows = [r for r in rows if r.get("created_at", "") >= frm]
    if to:
        rows = [r for r in rows if r.get("created_at", "") <= to]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)
