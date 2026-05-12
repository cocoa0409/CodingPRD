"""External-event ingress and audit-log query."""

from flask import Blueprint, request

import db
from middleware import require_role
from response import parse_pagination, success, success_list
from services import events
from services.serializers import serialize_audit_log, serialize_external_event

bp = Blueprint("events_audit", __name__)


@bp.post("/_events/emit")
def emit():
    require_role("PlatformAdmin")
    record, _was_dup = events.emit_event(request.get_json(silent=True))
    return success(serialize_external_event(record), 200)


@bp.get("/audit-logs")
def list_audit():
    require_role("PlatformAdmin")
    limit, offset = parse_pagination(request.args)
    filters = {
        "target_entity": request.args.get("target_entity"),
        "target_id": request.args.get("target_id"),
        "action": request.args.get("action"),
    }
    use = {k: v for k, v in filters.items() if v is not None}
    rows, total = db.query("audit_logs", filters=use, limit=limit, offset=offset)
    return success_list([serialize_audit_log(r) for r in rows], total, limit, offset)
