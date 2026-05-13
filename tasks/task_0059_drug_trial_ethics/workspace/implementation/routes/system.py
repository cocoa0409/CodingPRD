from __future__ import annotations

"""Audit-log listing + test-harness clock/sweep endpoints."""

from flask import Blueprint, g, request

import db
import clock
from errors import ERR_FIELD_VALIDATION, raise_error
from middleware import require_role
from response import success_array, success_object
from serializers import serialize_audit_log
import services_state as svc
from validation import get_json_body, get_pagination, require_datetime, sort_default


bp = Blueprint("system", __name__)


# ---------------------------------------------------------------------------
# GET /ethics/audit-logs
# ---------------------------------------------------------------------------
@bp.get("/ethics/audit-logs")
def list_audit_logs():
    require_role({"Secretary", "RegulatoryWatcher"})
    limit, offset = get_pagination()
    event_type = request.args.get("event_type")
    subject_entity = request.args.get("subject_entity")
    subject_id = request.args.get("subject_id")
    rows = list(db.audit_logs.values())
    if event_type:
        rows = [r for r in rows if r["event_type"] == event_type]
    if subject_entity:
        rows = [r for r in rows if r["subject_entity"] == subject_entity]
    if subject_id:
        rows = [r for r in rows if r["subject_id"] == subject_id]
    rows = sort_default(rows)
    total = len(rows)
    page = svc.paginate(rows, limit, offset)
    return success_array([serialize_audit_log(r) for r in page],
                         limit=limit, offset=offset, total_count=total)


# ---------------------------------------------------------------------------
# POST /ethics/_clock/advance
# ---------------------------------------------------------------------------
@bp.post("/ethics/_clock/advance")
def advance_clock():
    require_role({"Secretary"})
    body = get_json_body()
    target = require_datetime(body, "target_timestamp")
    clock.advance_to(clock.parse_iso(target))
    return success_object({"current_time": clock.iso()})


# ---------------------------------------------------------------------------
# POST /ethics/_sweep/run
# ---------------------------------------------------------------------------
@bp.post("/ethics/_sweep/run")
def run_sweep():
    require_role({"Secretary"})
    with db.lock:
        flipped = svc.run_expiry_sweep(g.user_role, g.user_id)
    return success_object({"flipped_count": flipped})
