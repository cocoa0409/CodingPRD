"""HardshipWithdrawal routes."""

from flask import Blueprint, request, g

from middleware import require_role, require_self_participant
from config import (
    ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT,
)
from services import hardship_service, lookups, serializers
import response as resp
from utils import lock


hardships_bp = Blueprint("hardships", __name__)


@hardships_bp.post("/plans/<plan_id>/participants/<participant_id>/hardship-withdrawals")
def request_hardship(plan_id, participant_id):
    require_role(ROLE_PARTICIPANT)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        body = request.get_json(silent=True) or {}
        h = hardship_service.request_hardship(plan, participant, body, g.user_id)
        view = serializers.hardship_view(h)
    return resp.success(view, status_code=201)


@hardships_bp.get("/plans/<plan_id>/participants/<participant_id>/hardship-withdrawals")
def list_hardships(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT)
    limit, offset = resp.parse_pagination(request.args)
    status_filter = request.args.get("status")
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        items, total = hardship_service.list_hardships(plan, participant, limit, offset, status_filter)
        views = [serializers.hardship_view(h) for h in items]
    return resp.success_list(views, total, limit, offset)


@hardships_bp.post("/plans/<plan_id>/participants/<participant_id>/hardship-withdrawals/<withdrawal_id>/approve")
def approve_hardship(plan_id, participant_id, withdrawal_id):
    require_role(ROLE_COMPLIANCE)
    with lock():
        plan, participant, h = lookups.resolve_hardship_path(plan_id, participant_id, withdrawal_id)
        body = request.get_json(silent=True) or {}
        h = hardship_service.approve_hardship(plan, participant, h, body, g.user_id)
        view = serializers.hardship_view(h)
    return resp.success(view)


@hardships_bp.post("/plans/<plan_id>/participants/<participant_id>/hardship-withdrawals/<withdrawal_id>/deny")
def deny_hardship(plan_id, participant_id, withdrawal_id):
    require_role(ROLE_COMPLIANCE)
    with lock():
        plan, participant, h = lookups.resolve_hardship_path(plan_id, participant_id, withdrawal_id)
        body = request.get_json(silent=True) or {}
        h = hardship_service.deny_hardship(plan, participant, h, body)
        view = serializers.hardship_view(h)
    return resp.success(view)
