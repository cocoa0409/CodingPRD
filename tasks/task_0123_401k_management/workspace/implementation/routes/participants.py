"""Participant routes."""

from flask import Blueprint, request, g

from middleware import require_role, require_self_participant
from config import (
    ROLE_PLAN_ADMIN, ROLE_PAYROLL, ROLE_COMPLIANCE, ROLE_PARTICIPANT,
)
from services import participant_service, lookups, serializers
from services.vesting import lazy_refresh_vested_snapshot
import response as resp
from utils import lock


participants_bp = Blueprint("participants", __name__)


@participants_bp.post("/plans/<plan_id>/participants")
def enroll(plan_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan = lookups.get_plan(plan_id)
        body = request.get_json(silent=True) or {}
        participant = participant_service.enroll(plan, body)
        view = serializers.participant_view(participant)
    return resp.success(view, status_code=201)


@participants_bp.get("/plans/<plan_id>/participants")
def list_participants(plan_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PAYROLL)
    limit, offset = resp.parse_pagination(request.args)
    status_filter = request.args.get("status")
    with lock():
        plan = lookups.get_plan(plan_id)
        items, total = participant_service.list_participants(plan, limit, offset, status_filter)
        views = [serializers.participant_view(p) for p in items]
    return resp.success_list(views, total, limit, offset)


@participants_bp.get("/plans/<plan_id>/participants/<participant_id>")
def get_participant(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PAYROLL)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        # Lazy refresh of vested_pct_snapshot per §2.12
        lazy_refresh_vested_snapshot(plan, participant)
        view = serializers.participant_view(participant)
    return resp.success(view)


@participants_bp.post("/plans/<plan_id>/participants/<participant_id>/activate")
def activate_participant(plan_id, participant_id):
    require_role(ROLE_PAYROLL)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        body = request.get_json(silent=True) or {}
        participant = participant_service.activate_participant(plan, participant, body)
        view = serializers.participant_view(participant)
    return resp.success(view)


@participants_bp.post("/plans/<plan_id>/participants/<participant_id>/terminate")
def terminate_participant(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        body = request.get_json(silent=True) or {}
        participant = participant_service.terminate_participant(plan, participant, body)
        view = serializers.participant_view(participant)
    return resp.success(view)


@participants_bp.patch("/plans/<plan_id>/participants/<participant_id>/deferral")
def update_deferral(plan_id, participant_id):
    require_role(ROLE_PARTICIPANT, ROLE_PAYROLL)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        body = request.get_json(silent=True) or {}
        participant = participant_service.update_deferral(plan, participant, body)
        view = serializers.participant_view(participant)
    return resp.success(view)
