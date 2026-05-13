"""SyncEvent routes."""

from flask import Blueprint, request

import db
import response as resp
from middleware import require_auth, require_role

bp = Blueprint("sync_events", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/sync-events", methods=["GET"])
def list_():
    require_role("PlatformAdmin", "Supervisor")
    limit, offset = resp.parse_pagination()
    wo_id = request.args.get("work_order_id")
    event_type = request.args.get("event_type")
    platform = request.args.get("target_platform")
    delivery_status = request.args.get("delivery_status")
    with db.LOCK:
        rows = list(db.all_rows("sync_events"))
        if wo_id is not None:
            rows = [r for r in rows if r.get("work_order_id") == wo_id]
        if event_type is not None:
            rows = [r for r in rows if r.get("event_type") == event_type]
        if platform is not None:
            rows = [r for r in rows if r.get("target_platform") == platform]
        if delivery_status is not None:
            rows = [r for r in rows if r.get("delivery_status") == delivery_status]
        rows.sort(key=lambda r: r["emitted_at"])
        total = len(rows)
        rows = rows[offset: offset + limit]
    return resp.success_list(rows, total, limit, offset)
