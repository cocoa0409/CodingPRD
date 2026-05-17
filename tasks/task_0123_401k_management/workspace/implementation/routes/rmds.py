"""RMDSchedule routes."""

from flask import Blueprint, request

from middleware import require_role, require_self_participant
from config import (
    ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT,
)
from services import rmd_service, lookups, serializers
import response as resp
from utils import lock


rmds_bp = Blueprint("rmds", __name__)


@rmds_bp.post("/plans/<plan_id>/participants/<participant_id>/rmd-schedules")
def schedule_rmd(plan_id, participant_id):
    require_role(ROLE_COMPLIANCE)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        body = request.get_json(silent=True) or {}
        r = rmd_service.schedule_rmd(plan, participant, body)
        view = serializers.rmd_view(r)
    return resp.success(view, status_code=201)


@rmds_bp.get("/plans/<plan_id>/participants/<participant_id>/rmd-schedules")
def list_rmds(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT)
    limit, offset = resp.parse_pagination(request.args)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        items, total = rmd_service.list_rmds(plan, participant, limit, offset)
        views = [serializers.rmd_view(r) for r in items]
    return resp.success_list(views, total, limit, offset)


@rmds_bp.post("/plans/<plan_id>/participants/<participant_id>/rmd-schedules/<schedule_id>/fulfill")
def fulfill_rmd(plan_id, participant_id, schedule_id):
    require_role(ROLE_COMPLIANCE)
    with lock():
        plan, participant, r = lookups.resolve_rmd_path(plan_id, participant_id, schedule_id)
        body = request.get_json(silent=True) or {}
        r = rmd_service.fulfill_rmd(plan, participant, r, body)
        view = serializers.rmd_view(r)
    return resp.success(view)
