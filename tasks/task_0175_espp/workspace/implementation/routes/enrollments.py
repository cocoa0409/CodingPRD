"""Enrollment routes."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.serializers import enrollment_view
from services.enrollment_service import (
    create_enrollment,
    get_enrollment_or_404,
    patch_enrollment,
    withdraw_enrollment,
)


bp = Blueprint("enrollments", __name__)


@bp.route("/offering-periods/<offering_period_id>/enrollments", methods=["POST"])
@require_roles("Participant")
def post_enrollment(offering_period_id: str):
    payload = get_json_body()
    enrollment = create_enrollment(
        offering_period_id=offering_period_id,
        participant_id=current_user_id(),
        payload=payload,
    )
    return success_response(enrollment_view(enrollment), status=201)


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
@require_roles("PlanAdministrator", "PayrollAgent", "Participant", "TaxAuthority")
def get_one(enrollment_id: str):
    e = get_enrollment_or_404(enrollment_id)
    return success_response(enrollment_view(e))


@bp.route("/enrollments/<enrollment_id>", methods=["PATCH"])
@require_roles("Participant")
def patch_one(enrollment_id: str):
    payload = get_json_body()
    e = patch_enrollment(
        enrollment_id=enrollment_id,
        acting_user_id=current_user_id(),
        payload=payload,
    )
    return success_response(enrollment_view(e))


@bp.route("/enrollments/<enrollment_id>/withdraw", methods=["POST"])
@require_roles("Participant")
def post_withdraw(enrollment_id: str):
    e = withdraw_enrollment(
        enrollment_id=enrollment_id, acting_user_id=current_user_id()
    )
    return success_response(enrollment_view(e))
