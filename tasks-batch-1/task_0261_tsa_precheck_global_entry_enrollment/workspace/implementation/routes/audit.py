"""Audit trail reads (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_auth
from response import ok_array
from routes._helpers import (
    order_by_created,
    paginate,
    parse_pagination,
    serialize_list,
)
from services.lookups import get_or_404

bp = Blueprint("audit", __name__)

AUDIT_READ_ROLES = ["SchedulingAdmin", "VettingOfficer", "AppealsOfficer", "Auditor"]


@bp.route("/applications/<app_id>/audit-events", methods=["GET"])
def list_audit_events(app_id):
    require_auth(AUDIT_READ_ROLES)
    get_or_404(db.applications, app_id, "Application")
    limit, offset = parse_pagination()
    items = [e for e in db.audit_events.values() if e.get("application_id") == app_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
