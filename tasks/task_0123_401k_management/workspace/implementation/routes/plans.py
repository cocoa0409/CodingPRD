"""Plan routes."""

from flask import Blueprint, request, g

from middleware import require_role
from config import (
    ROLE_PLAN_ADMIN, ROLE_PAYROLL, ROLE_COMPLIANCE, ROLE_PARTICIPANT,
)
from services import plan_service, lookups, serializers
import response as resp
from utils import lock


plans_bp = Blueprint("plans", __name__)


@plans_bp.post("/plans")
def create_plan():
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan = plan_service.create_plan(request.get_json(silent=True) or {})
    return resp.success(serializers.plan_view(plan), status_code=201)


@plans_bp.get("/plans")
def list_plans():
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PAYROLL)
    limit, offset = resp.parse_pagination(request.args)
    with lock():
        items, total = plan_service.list_plans(limit, offset)
        views = [serializers.plan_view(p) for p in items]
    return resp.success_list(views, total, limit, offset)


@plans_bp.get("/plans/<plan_id>")
def get_plan(plan_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PAYROLL)
    with lock():
        plan = lookups.get_plan(plan_id)
        view = serializers.plan_view(plan)
    return resp.success(view)


@plans_bp.post("/plans/<plan_id>/activate")
def activate_plan(plan_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan = lookups.get_plan(plan_id)
        body = request.get_json(silent=True) or {}
        plan = plan_service.activate_plan(plan, body)
        view = serializers.plan_view(plan)
    return resp.success(view)


@plans_bp.post("/plans/<plan_id>/freeze")
def freeze_plan(plan_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan = lookups.get_plan(plan_id)
        body = request.get_json(silent=True) or {}
        plan = plan_service.freeze_plan(plan, body)
        view = serializers.plan_view(plan)
    return resp.success(view)


@plans_bp.post("/plans/<plan_id>/advance-vesting-epoch")
def advance_epoch(plan_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan = lookups.get_plan(plan_id)
        body = request.get_json(silent=True) or {}
        plan = plan_service.advance_vesting_epoch(plan, body)
        view = serializers.plan_view(plan)
    return resp.success(view)


@plans_bp.post("/plans/<plan_id>/_clock/advance")
def advance_clock(plan_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan = lookups.get_plan(plan_id)
        body = request.get_json(silent=True) or {}
        clock = plan_service.advance_clock(plan, body)
        view = serializers.plan_clock_view(clock)
    return resp.success(view)
