"""ContributionRecord routes."""

from flask import Blueprint, request, g

from middleware import require_role, require_self_participant
from config import (
    ROLE_PLAN_ADMIN, ROLE_PAYROLL, ROLE_COMPLIANCE, ROLE_PARTICIPANT,
)
from services import contribution_service, lookups, serializers, sod
import response as resp
from utils import lock


contributions_bp = Blueprint("contributions", __name__)


@contributions_bp.post("/plans/<plan_id>/participants/<participant_id>/contribution-records")
def post_contribution(plan_id, participant_id):
    require_role(ROLE_PAYROLL)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        body = request.get_json(silent=True) or {}
        record = contribution_service.post_contribution(plan, participant, body)
        # Audit for SoD against later loan approvals
        sod.record_contribution_post(g.user_id, plan_id, participant_id, plan.get("plan_year", 0))
        view = serializers.contribution_view(record)
    return resp.success(view, status_code=201)


@contributions_bp.get("/plans/<plan_id>/participants/<participant_id>/contribution-records")
def list_contributions(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PAYROLL, ROLE_PARTICIPANT)
    limit, offset = resp.parse_pagination(request.args)
    year = request.args.get("year")
    year_int = None
    if year is not None:
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            year_int = None
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        items, total = contribution_service.list_contributions(plan, participant, limit, offset, year_int)
        views = [serializers.contribution_view(c) for c in items]
    return resp.success_list(views, total, limit, offset)
