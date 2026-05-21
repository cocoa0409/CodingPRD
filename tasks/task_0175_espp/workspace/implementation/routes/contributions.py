"""Contribution routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import contribution_view
from services.contribution_service import (
    list_contributions_for_enrollment,
    post_contribution,
)
from services.enrollment_service import get_enrollment_or_404


bp = Blueprint("contributions", __name__)


@bp.route("/enrollments/<enrollment_id>/contributions", methods=["POST"])
@require_roles("PayrollAgent")
def post_contrib(enrollment_id: str):
    payload = get_json_body()
    c = post_contribution(
        enrollment_id=enrollment_id,
        poster_user_id=current_user_id(),
        payload=payload,
    )
    return success_response(contribution_view(c), status=201)


@bp.route("/enrollments/<enrollment_id>/contributions", methods=["GET"])
@require_roles("PlanAdministrator", "PayrollAgent", "Participant", "TaxAuthority")
def list_contribs(enrollment_id: str):
    # Ensure enrollment exists first.
    get_enrollment_or_404(enrollment_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = list_contributions_for_enrollment(
        enrollment_id, status_filter=status_filter
    )
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        [contribution_view(c) for c in sliced],
        status=200,
        response_type="array",
        pagination=meta,
    )
