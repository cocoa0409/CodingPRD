"""AuditEvent listing routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..errors import err_not_found
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope
from ..serializers import view_audit_event
from ..store import get_store
from ._helpers import enforce_employee_ownership


bp_audit = Blueprint("audit", __name__)


@bp_audit.route("/employees/<employee_id>/audit-events", methods=["GET"])
@require_roles("HRStaff", "EmployerRep", "Employee")
def list_audit_events_route(user_id, role, employee_id):
    limit, offset = parse_pagination()
    store = get_store()
    if employee_id not in store.employees:
        raise err_not_found("Employee not found.")
    enforce_employee_ownership(role, user_id, employee_id)

    items = [a for a in store.audit_events.values() if a["subject_employee_id"] == employee_id]
    # Append-only, ordered by occurred_at ASC, with deterministic tiebreak by _seq.
    items.sort(key=lambda a: (a["occurred_at"], a["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(make_array_envelope(
        [view_audit_event(a) for a in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
