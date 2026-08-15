"""AuditEvent endpoint: append-only trail per case."""
from flask import Blueprint

import db
from routes.helpers import paginate, lookup, any_authenticated

bp = Blueprint("audit", __name__)


@bp.get("/api/utilization-cases/<cid>/audit-events")
def list_audit_events(cid):
    any_authenticated()
    lookup(db.utilization_cases, cid, "UtilizationCase")
    items = sorted(
        (e for e in db.audit_events.values() if e["case_id"] == cid),
        key=lambda e: e["created_at"],
    )
    return paginate(items)
