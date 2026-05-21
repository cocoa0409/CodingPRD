"""ReverificationEvent listing routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope
from ..serializers import view_reverification_event
from ..services.reverification import list_reverification_events
from ._helpers import enforce_employee_ownership


bp_reverification = Blueprint("reverification", __name__)


@bp_reverification.route("/employees/<employee_id>/reverification-events", methods=["GET"])
@require_roles("HRStaff", "EmployerRep", "Employee")
def list_reverification_events_route(user_id, role, employee_id):
    limit, offset = parse_pagination()
    enforce_employee_ownership(role, user_id, employee_id)
    filters = {"status": request.args.get("status")}
    items = list_reverification_events(employee_id, filters)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(make_array_envelope(
        [view_reverification_event(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )), 200
