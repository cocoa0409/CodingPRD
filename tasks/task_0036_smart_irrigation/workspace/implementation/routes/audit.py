"""Audit log query routes."""

from flask import Blueprint, g, request

from clock import parse_iso
from db import DB, LOCK
from errors import forbidden, validation_error
from response import success_array
from services.common import (
    paginate,
    parse_pagination,
    to_aware_utc,
)
from services.serializers import audit_log_view


bp = Blueprint("audit", __name__)


@bp.route("/audit-logs", methods=["GET"])
def list_audit():
    if g.role not in {"PlatformAdmin", "WaterAdmin"}:
        raise forbidden()
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    action_type = request.args.get("action_type")
    since_raw = request.args.get("since")
    until_raw = request.args.get("until")
    since = None
    until = None
    if since_raw:
        try:
            since = parse_iso(since_raw)
        except Exception:
            raise validation_error("since must be ISO 8601")
    if until_raw:
        try:
            until = parse_iso(until_raw)
        except Exception:
            raise validation_error("until must be ISO 8601")

    with LOCK:
        items = list(DB.audit_logs)
        if subject_type:
            items = [a for a in items if a.get("subject_type") == subject_type]
        if action_type:
            items = [a for a in items if a.get("action_type") == action_type]
        if since:
            items = [a for a in items if to_aware_utc(a.get("created_at")) >= since]
        if until:
            items = [a for a in items if to_aware_utc(a.get("created_at")) <= until]
        items.sort(key=lambda r: r.get("created_at"))
        page, total, has_more = paginate(items, limit, offset)
        data = [audit_log_view(a) for a in page]
    return success_array(data, limit, offset, total, has_more)
