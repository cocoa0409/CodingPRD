"""/plans routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import APIError, err_pagination_invalid
from core.pagination import paginate, parse_pagination
from core.serializers import plan_view
from services.participant_service import dilution_preview
from services.plan_service import (
    activate_plan,
    create_plan,
    get_plan_or_404,
    list_plans,
    patch_plan,
    terminate_plan,
)


bp = Blueprint("plans", __name__)


@bp.route("/plans", methods=["POST"])
@require_roles("PlanAdministrator")
def post_plan():
    payload = get_json_body()
    plan = create_plan(payload)
    return success_response(plan_view(plan), status=201, response_type="object")


@bp.route("/plans", methods=["GET"])
@require_roles("PlanAdministrator", "TaxAuthority")
def get_plans():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = list_plans(status_filter)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        [plan_view(p) for p in sliced],
        status=200,
        response_type="array",
        pagination=meta,
    )


@bp.route("/plans/<plan_id>", methods=["GET"])
@require_roles("PlanAdministrator", "PayrollAgent", "Participant", "TaxAuthority")
def get_one_plan(plan_id: str):
    plan = get_plan_or_404(plan_id)
    return success_response(plan_view(plan))


@bp.route("/plans/<plan_id>", methods=["PATCH"])
@require_roles("PlanAdministrator")
def patch_one_plan(plan_id: str):
    payload = get_json_body()
    plan = patch_plan(plan_id, payload)
    return success_response(plan_view(plan))


@bp.route("/plans/<plan_id>/activate", methods=["POST"])
@require_roles("PlanAdministrator")
def post_activate(plan_id: str):
    plan = activate_plan(plan_id)
    return success_response(plan_view(plan))


@bp.route("/plans/<plan_id>/terminate", methods=["POST"])
@require_roles("PlanAdministrator")
def post_terminate(plan_id: str):
    plan = terminate_plan(plan_id)
    return success_response(plan_view(plan))


@bp.route("/plans/<plan_id>/dilution-preview", methods=["GET"])
@require_roles("PlanAdministrator")
def get_dilution_preview(plan_id: str):
    # Ensure plan exists first.
    get_plan_or_404(plan_id)
    raw = request.args.get("eligible_employee_count")
    if raw is None:
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "eligible_employee_count is required.",
            422,
        )
    try:
        eligible = int(raw)
    except (TypeError, ValueError):
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "eligible_employee_count must be an integer.",
            422,
        )
    if eligible < 0:
        raise APIError(
            "ERR_PERIOD_LENGTH_OUT_OF_RANGE",
            "eligible_employee_count must be >= 0.",
            422,
        )
    result = dilution_preview(plan_id=plan_id, eligible_employee_count=eligible)
    return success_response(result)
