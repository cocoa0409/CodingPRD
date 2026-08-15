"""HACCP plan + CCP endpoints."""

from flask import Blueprint, request

from db import store, new_id
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from validation import get_body, req_enum, req_string, req_int, opt_number
from errors import (raise_error, ERR_NOT_FOUND, ERR_PLAN_INVALID_STATE,
                    ERR_DUPLICATE_ACTIVE_PLAN, ERR_CCP_LIMIT_INVALID, ERR_PLAN_HAS_NO_CCP)
from serializers import haccp_plan_out, ccp_out
from services import touch

bp = Blueprint("haccp", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")
PROCESS_TYPES = {"SLAUGHTER", "RAW_GROUND", "RAW_INTACT", "COOKED_RTE"}
HAZARD_CATEGORIES = {"BIOLOGICAL", "CHEMICAL", "PHYSICAL"}


def _get_plan(plan_id):
    plan = store.haccp_plans.get(plan_id)
    if not plan:
        raise_error(ERR_NOT_FOUND, "HACCP plan not found")
    return plan


@bp.route("/plants/<pid>/haccp-plans", methods=["POST"])
def create_plan(pid):
    user_id, _ = require_roles("QAManager")
    body = get_body()
    process_type = req_enum(body, "process_type", PROCESS_TYPES)
    plant = store.plants.get(pid)
    if not plant:
        raise_error(ERR_NOT_FOUND, "Plant not found")
    # At most one plan per (plant, process_type) in DRAFT/SUBMITTED/APPROVED
    for p in store.haccp_plans.values():
        if p["plant_id"] == pid and p["process_type"] == process_type and p["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            raise_error(ERR_DUPLICATE_ACTIVE_PLAN, "An active plan already exists for this process type")
    now = store.now_iso()
    plan = {
        "id": new_id(),
        "plant_id": pid,
        "process_type": process_type,
        "status": "DRAFT",
        "revision_number": 0,
        "rejection_reason": None,
        "approved_by": None,
        "submitted_at": None,
        "approved_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.haccp_plans[plan["id"]] = plan
    return success_object(haccp_plan_out(plan), 201)


@bp.route("/haccp-plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_roles(*READ_ROLES)
    return success_object(haccp_plan_out(_get_plan(pid)))


@bp.route("/haccp-plans", methods=["GET"])
def list_plans():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plant_id = request.args.get("plant_id")
    process_type = request.args.get("process_type")
    status = request.args.get("status")
    items = sorted(store.haccp_plans.values(), key=lambda p: (p["created_at"], p["id"]))
    if plant_id is not None:
        items = [p for p in items if p["plant_id"] == plant_id]
    if process_type is not None:
        items = [p for p in items if p["process_type"] == process_type]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([haccp_plan_out(p) for p in page], limit, offset, total)


@bp.route("/haccp-plans/<pid>/submit", methods=["POST"])
def submit_plan(pid):
    user_id, _ = require_roles("QAManager")
    get_body()
    plan = _get_plan(pid)
    if plan["status"] not in ("DRAFT", "REJECTED"):
        raise_error(ERR_PLAN_INVALID_STATE, "Plan must be DRAFT or REJECTED to submit")
    # Content check: at least one CCP
    has_ccp = any(c["haccp_plan_id"] == pid for c in store.ccps.values())
    if not has_ccp:
        raise_error(ERR_PLAN_HAS_NO_CCP, "Plan has no critical control points")
    if plan["status"] == "REJECTED":
        plan["revision_number"] += 1
        plan["rejection_reason"] = None
    plan["status"] = "SUBMITTED"
    plan["submitted_at"] = store.now_iso()
    touch(plan)
    return success_object(haccp_plan_out(plan))


@bp.route("/haccp-plans/<pid>/approve", methods=["POST"])
def approve_plan(pid):
    user_id, _ = require_roles("Inspector")
    get_body()
    plan = _get_plan(pid)
    if plan["status"] != "SUBMITTED":
        raise_error(ERR_PLAN_INVALID_STATE, "Plan must be SUBMITTED to approve")
    plan["status"] = "APPROVED"
    plan["approved_by"] = user_id
    plan["approved_at"] = store.now_iso()
    touch(plan)
    return success_object(haccp_plan_out(plan))


@bp.route("/haccp-plans/<pid>/reject", methods=["POST"])
def reject_plan(pid):
    user_id, _ = require_roles("Inspector")
    body = get_body()
    reason = req_string(body, "rejection_reason")
    plan = _get_plan(pid)
    if plan["status"] != "SUBMITTED":
        raise_error(ERR_PLAN_INVALID_STATE, "Plan must be SUBMITTED to reject")
    plan["status"] = "REJECTED"
    plan["rejection_reason"] = reason
    touch(plan)
    return success_object(haccp_plan_out(plan))


@bp.route("/haccp-plans/<pid>/activate", methods=["POST"])
def activate_plan(pid):
    user_id, _ = require_roles("QAManager")
    get_body()
    plan = _get_plan(pid)
    if plan["status"] != "APPROVED":
        raise_error(ERR_PLAN_INVALID_STATE, "Plan must be APPROVED to activate")
    # Supersede currently EFFECTIVE sibling of same (plant, process_type)
    for p in store.haccp_plans.values():
        if (p["id"] != pid and p["plant_id"] == plan["plant_id"]
                and p["process_type"] == plan["process_type"] and p["status"] == "EFFECTIVE"):
            p["status"] = "SUPERSEDED"
            touch(p)
    plan["status"] = "EFFECTIVE"
    touch(plan)
    return success_object(haccp_plan_out(plan))


# ---------------------------------------------------------------------------
# CCP endpoints
# ---------------------------------------------------------------------------

@bp.route("/haccp-plans/<pid>/ccps", methods=["POST"])
def create_ccp(pid):
    user_id, _ = require_roles("QAManager")
    body = get_body()
    ccp_code = req_string(body, "ccp_code")
    hazard_category = req_enum(body, "hazard_category", HAZARD_CATEGORIES)
    description = req_string(body, "description")
    monitoring_frequency_minutes = req_int(body, "monitoring_frequency_minutes", gt=0)
    critical_limit_min_f = opt_number(body, "critical_limit_min_f")
    critical_limit_max_f = opt_number(body, "critical_limit_max_f")

    plan = _get_plan(pid)
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_INVALID_STATE, "CCPs can only be added to a DRAFT plan")

    # Business constraint: at least one limit, and min < max when both present
    if critical_limit_min_f is None and critical_limit_max_f is None:
        raise_error(ERR_CCP_LIMIT_INVALID, "At least one critical limit must be supplied")
    if critical_limit_min_f is not None and critical_limit_max_f is not None:
        if not (critical_limit_min_f < critical_limit_max_f):
            raise_error(ERR_CCP_LIMIT_INVALID, "critical_limit_min_f must be strictly below critical_limit_max_f")

    # ccp_code unique within plan
    for c in store.ccps.values():
        if c["haccp_plan_id"] == pid and c["ccp_code"] == ccp_code:
            from errors import ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST, "ccp_code must be unique within the plan")

    deviation_severity = "MAJOR" if hazard_category == "BIOLOGICAL" else "MINOR"
    now = store.now_iso()
    ccp = {
        "id": new_id(),
        "haccp_plan_id": pid,
        "ccp_code": ccp_code,
        "hazard_category": hazard_category,
        "description": description,
        "critical_limit_min_f": critical_limit_min_f,
        "critical_limit_max_f": critical_limit_max_f,
        "monitoring_frequency_minutes": monitoring_frequency_minutes,
        "deviation_severity": deviation_severity,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.ccps[ccp["id"]] = ccp
    return success_object(ccp_out(ccp), 201)


@bp.route("/ccps/<cid>", methods=["GET"])
def get_ccp(cid):
    require_roles(*READ_ROLES)
    ccp = store.ccps.get(cid)
    if not ccp:
        raise_error(ERR_NOT_FOUND, "CCP not found")
    return success_object(ccp_out(ccp))


@bp.route("/ccps", methods=["GET"])
def list_ccps():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    plan_id = request.args.get("haccp_plan_id")
    hazard = request.args.get("hazard_category")
    items = sorted(store.ccps.values(), key=lambda c: (c["created_at"], c["id"]))
    if plan_id is not None:
        items = [c for c in items if c["haccp_plan_id"] == plan_id]
    if hazard is not None:
        items = [c for c in items if c["hazard_category"] == hazard]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ccp_out(c) for c in page], limit, offset, total)
