"""VestingSnapshot routes."""

from flask import Blueprint, request

from middleware import require_role, require_self_participant
from config import (
    ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT,
)
from services import vesting_snapshot_service, lookups, serializers
import response as resp
from utils import lock


vesting_bp = Blueprint("vesting", __name__)


@vesting_bp.post("/plans/<plan_id>/participants/<participant_id>/vesting-snapshots")
def create_snapshot(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        snap = vesting_snapshot_service.create_snapshot(plan, participant)
        view = serializers.vesting_snapshot_view(snap)
    return resp.success(view, status_code=201)


@vesting_bp.get("/plans/<plan_id>/participants/<participant_id>/vesting-snapshots")
def list_snapshots(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT)
    limit, offset = resp.parse_pagination(request.args)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        items, total = vesting_snapshot_service.list_snapshots(plan, participant, limit, offset)
        views = [serializers.vesting_snapshot_view(v) for v in items]
    return resp.success_list(views, total, limit, offset)
