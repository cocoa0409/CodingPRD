"""Inspection endpoints."""

import uuid
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTION_NOT_SCHEDULED,
    ERR_INSPECTION_TOO_SOON,
    ERR_PLAN_NOT_ACTIVE,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, parse_iso, check_enum
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_inspection,
    paginate,
    recompute_permit_rollup,
    CA_DEADLINE_DAYS,
    SEVERITIES,
)

bp = Blueprint("inspections", __name__)

MIN_GAP_DAYS = 7


@bp.route("/npdes/inspections", methods=["POST"])
def create_inspection():
    user_id, role = require_roles(["FacilityInspector"])
    body = get_body()
    require_fields(body, ["plan_id", "scheduled_for"])
    plan = db.swppp_plans.get(body["plan_id"])
    if plan is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "StormwaterPlan not found")
    scheduled_for = parse_iso(body["scheduled_for"], "scheduled_for")

    # Spacing rule: no other non-CANCELLED inspection of the same plan strictly
    # less than 7 days away (exactly 7 days allowed).
    gap = timedelta(days=MIN_GAP_DAYS)
    for other in db.inspections.values():
        if other["plan_id"] != plan["id"] or other["status"] == "CANCELLED":
            continue
        delta = abs(scheduled_for - other["scheduled_for"])
        if delta < gap:
            raise err(ERR_INSPECTION_TOO_SOON, 409, "Another inspection is scheduled within 7 days")

    insp = base_entity("Inspection")
    insp["id"] = str(uuid.uuid4())
    insp.update(
        {
            "plan_id": plan["id"],
            "scheduled_for": scheduled_for,
            "status": "SCHEDULED",
            "inspector_user_id": user_id,
            "completed_at": None,
            "findings": [],
        }
    )
    db.inspections[insp["id"]] = insp
    append_audit("Inspection", insp["id"], "INSPECTION_SCHEDULED", user_id, role)
    return success(serialize_inspection(insp), 201)


@bp.route("/npdes/inspections", methods=["GET"])
def list_inspections():
    require_roles(["Any"])
    items = list(db.inspections.values())
    plan_id = request.args.get("plan_id")
    if plan_id:
        items = [i for i in items if i["plan_id"] == plan_id]
    status = request.args.get("status")
    if status:
        items = [i for i in items if i["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_inspection(i) for i in page], total, limit, offset)


@bp.route("/npdes/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    require_roles(["Any"])
    insp = db.inspections.get(iid)
    if insp is None:
        raise err(ERR_INSPECTION_NOT_FOUND, 404, "Inspection not found")
    return success(serialize_inspection(insp), 200)


@bp.route("/npdes/inspections/<iid>/complete", methods=["POST"])
def complete_inspection(iid):
    user_id, role = require_roles(["FacilityInspector"])
    insp = db.inspections.get(iid)
    if insp is None:
        raise err(ERR_INSPECTION_NOT_FOUND, 404, "Inspection not found")
    if insp["status"] != "SCHEDULED":
        raise err(ERR_INSPECTION_NOT_SCHEDULED, 409, "Inspection is not SCHEDULED")
    plan = db.swppp_plans.get(insp["plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise err(ERR_PLAN_NOT_ACTIVE, 409, "Parent plan is not ACTIVE")

    body = get_body()
    if "findings" not in body or body["findings"] is None:
        raise err(ERR_INVALID_REQUEST, 400, "findings is required")
    findings = body["findings"]
    if not isinstance(findings, list):
        raise err(ERR_INVALID_REQUEST, 400, "findings must be a list")
    for f in findings:
        if not isinstance(f, dict) or "description" not in f or "severity" not in f:
            raise err(ERR_INVALID_REQUEST, 400, "each finding requires description and severity")
        check_enum(f["severity"], SEVERITIES, "severity")

    now = db.clock.now()
    insp["completed_at"] = now
    insp["findings"] = findings
    insp["status"] = "COMPLETED"
    touch(insp)

    permit_id = plan["permit_id"]
    # Each finding spawns an OPEN corrective action; each bumps the permit counters
    for f in findings:
        ca = base_entity("CorrectiveAction")
        ca["id"] = str(uuid.uuid4())
        ca.update(
            {
                "source_type": "INSPECTION",
                "inspection_id": insp["id"],
                "exceedance_id": None,
                "description": f["description"],
                "severity": f["severity"],
                "deadline_at": ca["created_at"] + timedelta(days=CA_DEADLINE_DAYS[f["severity"]]),
                "status": "OPEN",
                "resolved_at": None,
                "resolved_by_user_id": None,
                "actual_cost_cents": None,
                "verified_by_user_id": None,
            }
        )
        db.corrective_actions[ca["id"]] = ca
        append_audit("CorrectiveAction", ca["id"], "CA_CREATED", user_id, role)
        recompute_permit_rollup(permit_id)

    append_audit("Inspection", insp["id"], "INSPECTION_COMPLETED", user_id, role)
    return success(serialize_inspection(insp), 200)


@bp.route("/npdes/inspections/<iid>/cancel", methods=["POST"])
def cancel_inspection(iid):
    user_id, role = require_roles(["FacilityInspector"])
    insp = db.inspections.get(iid)
    if insp is None:
        raise err(ERR_INSPECTION_NOT_FOUND, 404, "Inspection not found")
    if insp["status"] != "SCHEDULED":
        raise err(ERR_INSPECTION_NOT_SCHEDULED, 409, "Inspection is not SCHEDULED")
    insp["status"] = "CANCELLED"
    touch(insp)
    append_audit("Inspection", insp["id"], "INSPECTION_CANCELLED", user_id, role)
    return success(serialize_inspection(insp), 200)
