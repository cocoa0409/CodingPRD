"""/foia/audit-entries — read-only audit log query."""

from __future__ import annotations

from flask import Blueprint, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array
from ..serializers import serialize_audit_entry
from ..store import store
from ..util import get_pagination, paginate


audit_bp = Blueprint("audit", __name__)


@audit_bp.get("/foia/audit-entries")
@require_auth({"Officer", "AppealAuthority"})
def list_audit():
    limit, offset = get_pagination()
    subject_type = flask_request.args.get("subject_type")
    subject_id = flask_request.args.get("subject_id")
    event_code = flask_request.args.get("event_code")
    items = list(store.audit_entries.values())
    if subject_type:
        items = [e for e in items if e["subject_type"] == subject_type]
    if subject_id:
        items = [e for e in items if e["subject_id"] == subject_id]
    if event_code:
        items = [e for e in items if e["event_code"] == event_code]
    items.sort(key=lambda e: e["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_audit_entry(e) for e in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )
