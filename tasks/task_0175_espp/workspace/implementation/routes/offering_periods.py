"""Offering period routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_not_found
from core.pagination import paginate, parse_pagination
from core.serializers import offering_period_view, purchase_view
from core.store import store
from services.offering_period_service import (
    get_offering_period_or_404,
    list_offering_periods_for_plan,
    patch_purchase_fmv,
    record_grant_fmv,
)
from services.plan_service import get_plan_or_404
from services.purchase_service import run_purchase_batch


bp = Blueprint("offering_periods", __name__)


@bp.route("/plans/<plan_id>/offering-periods", methods=["GET"])
@require_roles("PlanAdministrator", "PayrollAgent", "Participant", "TaxAuthority")
def list_for_plan(plan_id: str):
    get_plan_or_404(plan_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = list_offering_periods_for_plan(plan_id, status_filter=status_filter)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        [offering_period_view(o) for o in sliced],
        status=200,
        response_type="array",
        pagination=meta,
    )


@bp.route("/offering-periods/<offering_period_id>", methods=["GET"])
@require_roles("PlanAdministrator", "PayrollAgent", "Participant", "TaxAuthority")
def get_one(offering_period_id: str):
    op = get_offering_period_or_404(offering_period_id)
    return success_response(offering_period_view(op))


@bp.route(
    "/plans/<plan_id>/offering-periods/<offering_period_id>/grant-fmv",
    methods=["POST"],
)
@require_roles("PlanAdministrator")
def post_grant_fmv(plan_id: str, offering_period_id: str):
    payload = get_json_body()
    op = record_grant_fmv(
        plan_id=plan_id, offering_period_id=offering_period_id, payload=payload
    )
    return success_response(offering_period_view(op))


@bp.route("/offering-periods/<offering_period_id>/fmv", methods=["PATCH"])
@require_roles("PlanAdministrator")
def patch_fmv(offering_period_id: str):
    payload = get_json_body()
    op = patch_purchase_fmv(
        offering_period_id=offering_period_id, payload=payload
    )
    return success_response(offering_period_view(op))


@bp.route("/offering-periods/<offering_period_id>/run-purchase", methods=["POST"])
@require_roles("PlanAdministrator")
def post_run_purchase(offering_period_id: str):
    acting = current_user_id()
    result = run_purchase_batch(
        offering_period_id=offering_period_id, acting_user_id=acting
    )
    # Serialize purchases + forms for the response.
    body = {
        "offering_period_id": result["offering_period_id"],
        "purchases": [purchase_view(p) for p in result["purchases"]],
        "form_3922s": [dict(f) for f in result["form_3922s"]],
        "next_offering_period_id": result["next_offering_period_id"],
    }
    return success_response(body)
