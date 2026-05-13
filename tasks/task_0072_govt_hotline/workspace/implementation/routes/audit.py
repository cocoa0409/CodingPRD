"""Audit log routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role

bp = Blueprint("audit", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/audit-logs", methods=["GET"])
def list_():
    require_role("PlatformAdmin", "Supervisor")
    limit, offset = resp.parse_pagination()
    wo_id = request.args.get("work_order_id")
    action = request.args.get("action")
    with db.LOCK:
        rows = list(db.all_rows("audit_logs"))
        if wo_id is not None:
            rows = [r for r in rows if r.get("work_order_id") == wo_id]
        if action is not None:
            rows = [r for r in rows if r.get("action") == action]
        rows.sort(key=lambda r: r["occurred_at"])
        total = len(rows)
        rows = rows[offset: offset + limit]
    return resp.success_list(rows, total, limit, offset)
