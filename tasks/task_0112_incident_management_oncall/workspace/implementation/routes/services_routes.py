"""Service + service-scoped reverse-reachability lists + budget summary."""
from flask import Blueprint

import response
from db import db
from middleware import require_user_context, require_role, get_json_body, get_pagination
from services import budget
from services.common import require_str, require_int, optional_enum, stamp_create
from services.lookups import get_service
from services.serializers import (
    service_out, incident_out, window_out, policy_out, schedule_out,
)

bp = Blueprint("services", __name__)

ALL_ROLES = {"PlatformAdmin", "IncidentCommander", "ResponderUser"}
ADMIN_IC = {"PlatformAdmin", "IncidentCommander"}
TIERS = {"TIER_1", "TIER_2", "TIER_3"}


@bp.route("/services", methods=["POST"])
def create_service():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    tier = optional_enum(body, "tier", TIERS, "TIER_2")
    error_budget_minutes = require_int(body, "error_budget_minutes", minimum=1)
    with db.lock:
        svc = stamp_create({
            "name": name,
            "tier": tier,
            "error_budget_minutes": error_budget_minutes,
        })
        db.services[svc["id"]] = svc
    return response.success(service_out(svc), 201)


@bp.route("/services", methods=["GET"])
def list_services():
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        return response.list_response(list(db.services.values()), limit, offset, service_out)


@bp.route("/services/<sid>", methods=["GET"])
def get_one_service(sid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        svc = get_service(sid)
        return response.success(service_out(svc), 200)


@bp.route("/services/<sid>/budget-summary", methods=["GET"])
def budget_summary(sid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    with db.lock:
        svc = get_service(sid)
        consumed = budget.consumed_minutes(svc)
        event_cost = budget.event_cost_minutes(svc)
        remaining = max(0, svc["error_budget_minutes"] - consumed)
        status = budget.budget_status(svc, consumed)
        data = {
            "consumed_minutes": consumed,
            "event_cost_minutes": event_cost,
            "remaining_minutes": remaining,
            "budget_status": status,
        }
    return response.success(data, 200)


@bp.route("/services/<sid>/incidents", methods=["GET"])
def list_service_incidents(sid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        get_service(sid)
        rows = [i for i in db.incidents.values() if i["service_id"] == sid]
        return response.list_response(rows, limit, offset, incident_out)


@bp.route("/services/<sid>/maintenance-windows", methods=["GET"])
def list_service_windows(sid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    limit, offset = get_pagination()
    with db.lock:
        get_service(sid)
        rows = [w for w in db.windows.values() if w["service_id"] == sid]
        return response.list_response(rows, limit, offset, window_out)


@bp.route("/services/<sid>/escalation-policies", methods=["GET"])
def list_service_policies(sid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    limit, offset = get_pagination()
    with db.lock:
        get_service(sid)
        rows = [p for p in db.policies.values() if p["service_id"] == sid]
        return response.list_response(rows, limit, offset, policy_out)


@bp.route("/services/<sid>/on-call-schedules", methods=["GET"])
def list_service_schedules(sid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    limit, offset = get_pagination()
    with db.lock:
        get_service(sid)
        rows = [s for s in db.schedules.values() if s["service_id"] == sid]
        return response.list_response(rows, limit, offset, schedule_out)
