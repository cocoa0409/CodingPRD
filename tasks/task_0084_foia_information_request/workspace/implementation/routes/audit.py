"""Append-only audit trail listing (PRD §3.10)."""

from flask import Blueprint

import db
from helpers import get_or_404, serialize, parse_pagination, sort_by_creation, paginate
from middleware import require_roles
from response import ok_array

bp = Blueprint("audit", __name__)


@bp.get("/requests/<rid>/audit-events")
def list_audit_events(rid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    get_or_404(db.requests, rid)
    limit, offset = parse_pagination()
    items = sort_by_creation([e for e in db.audit_events.values() if e["request_id"] == rid])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("AuditEvent", e) for e in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)
