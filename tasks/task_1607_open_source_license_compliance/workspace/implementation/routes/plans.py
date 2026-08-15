"""RemediationPlan endpoints."""

from flask import Blueprint, request

from db import store, base_resource, touch, iso_fmt
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_REMEDIATION_PLAN_NOT_FOUND,
    ERR_VULNERABILITY_FINDING_NOT_FOUND, ERR_INVALID_PLAN_TYPE,
    ERR_INCOMPATIBLE_LICENSE, ERR_PRODUCT_BLOCKED, ERR_PLAN_NOT_PROPOSED,
    ERR_PLAN_NOT_APPROVED, ERR_PLAN_NOT_IN_PROGRESS, ERR_PLAN_NOT_ABANDONABLE,
    ERR_INVALID_REQUEST, ERR_COMPONENT_NOT_FOUND, ERR_SCAN_NOT_FOUND,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services.policy import effective_classification

bp = Blueprint("plans", __name__)

PLAN_TYPES = {"UPGRADE", "REPLACE", "PATCH", "MITIGATE_CONFIG", "ACCEPT_RISK"}
ENGINEERING_CAPACITY_DAYS = 365  # generous capacity ceiling


def plan_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _resolve(productId, planId=None):
    prod = store.products.get(productId)
    if not prod:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    plan = None
    if planId is not None:
        plan = store.plans.get(planId)
        if not plan or plan["product_id"] != productId:
            raise err(ERR_REMEDIATION_PLAN_NOT_FOUND, "RemediationPlan not found")
    return prod, plan


def _license_compatible(component):
    eff = effective_classification(component)
    return eff in ("PERMISSIVE", "WEAK_COPYLEFT")


@bp.route("/oss-products/<productId>/remediation-plans", methods=["POST"])
def create_plan(productId):
    require_roles("EngineeringManager")
    prod = store.products.get(productId)
    if not prod:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    body = get_json_body()
    finding_id = body.get("finding_id")
    plan_type = body.get("plan_type")
    if plan_type not in PLAN_TYPES:
        raise err(ERR_INVALID_PLAN_TYPE,
                  "plan_type must be UPGRADE, REPLACE, PATCH, MITIGATE_CONFIG, or ACCEPT_RISK")
    if not finding_id:
        raise err(ERR_INVALID_REQUEST, "finding_id is required")
    finding = store.findings.get(finding_id)
    if not finding or finding["product_id"] != productId:
        raise err(ERR_VULNERABILITY_FINDING_NOT_FOUND, "VulnerabilityFinding not found")

    effort = body.get("migration_effort_days")
    if effort is None:
        raise err(ERR_INVALID_REQUEST, "migration_effort_days is required")
    try:
        effort = int(effort)
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, "migration_effort_days must be an integer")
    if effort > ENGINEERING_CAPACITY_DAYS:
        from errors import ERR_CAPACITY_EXCEEDED
        raise err(ERR_CAPACITY_EXCEEDED,
                  "RemediationPlan migration_effort_days exceeds available engineering capacity")

    target_component_id = body.get("target_component_id")
    license_compat = None
    if target_component_id is not None:
        target = store.components.get(target_component_id)
        if not target:
            raise err(ERR_COMPONENT_NOT_FOUND, "Component not found")
        if plan_type in ("UPGRADE", "REPLACE"):
            if not _license_compatible(target):
                raise err(ERR_INCOMPATIBLE_LICENSE,
                          "target_component_id has PROHIBITED or incompatible license for remediation")
        license_compat = _license_compatible(target)

    plan = base_resource()
    plan.update({
        "product_id": productId,
        "finding_id": finding_id,
        "plan_type": plan_type,
        "target_component_id": target_component_id,
        "target_version": body.get("target_version"),
        "migration_effort_days": effort,
        "status": "PROPOSED",
        "actual_completion_at": None,
        "verification_scan_id": None,
        "license_compatibility_verified": license_compat,
    })
    store.plans[plan["id"]] = plan
    return success_obj(plan_view(plan), status=201)


@bp.route("/oss-products/<productId>/remediation-plans", methods=["GET"])
def list_plans(productId):
    get_auth()
    _resolve(productId)
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.plans.values() if p["product_id"] == productId]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([plan_view(p) for p in page], limit, offset, total)


@bp.route("/oss-products/<productId>/remediation-plans/<planId>", methods=["GET"])
def get_plan(productId, planId):
    get_auth()
    _, plan = _resolve(productId, planId)
    return success_obj(plan_view(plan))


@bp.route("/oss-products/<productId>/remediation-plans/<planId>/approve", methods=["POST"])
def approve_plan(productId, planId):
    require_roles("EngineeringManager")
    prod, plan = _resolve(productId, planId)
    if prod["compliance_posture"] == "BLOCKED":
        raise err(ERR_PRODUCT_BLOCKED, "Operation requires Product not in BLOCKED posture")
    if plan["status"] != "PROPOSED":
        raise err(ERR_PLAN_NOT_PROPOSED, "RemediationPlan must be PROPOSED")
    if plan["plan_type"] in ("UPGRADE", "REPLACE"):
        target = store.components.get(plan.get("target_component_id"))
        if not target or not _license_compatible(target):
            raise err(ERR_INCOMPATIBLE_LICENSE,
                      "target_component_id has PROHIBITED or incompatible license for remediation")
        plan["license_compatibility_verified"] = True
    plan["status"] = "APPROVED"
    touch(plan)
    finding = store.findings.get(plan["finding_id"])
    if finding:
        finding["remediation_status"] = "IN_PROGRESS"
        touch(finding)
    return success_obj(plan_view(plan))


@bp.route("/oss-products/<productId>/remediation-plans/<planId>/start", methods=["POST"])
def start_plan(productId, planId):
    require_roles("EngineeringManager")
    _, plan = _resolve(productId, planId)
    if plan["status"] != "APPROVED":
        raise err(ERR_PLAN_NOT_APPROVED, "RemediationPlan must be APPROVED")
    plan["status"] = "IN_PROGRESS"
    touch(plan)
    return success_obj(plan_view(plan))


@bp.route("/oss-products/<productId>/remediation-plans/<planId>/complete", methods=["POST"])
def complete_plan(productId, planId):
    require_roles("EngineeringManager")
    _, plan = _resolve(productId, planId)
    body = get_json_body()
    verification_scan_id = body.get("verification_scan_id")
    if not verification_scan_id:
        raise err(ERR_INVALID_REQUEST, "verification_scan_id is required")
    scan = store.scans.get(verification_scan_id)
    if not scan:
        raise err(ERR_SCAN_NOT_FOUND, "DependencyScan not found")
    if plan["status"] != "IN_PROGRESS":
        raise err(ERR_PLAN_NOT_IN_PROGRESS, "RemediationPlan must be IN_PROGRESS")
    if scan["status"] != "COMPLETED":
        raise err(ERR_INVALID_REQUEST,
                  "verification_scan_id must reference a COMPLETED scan showing vulnerability absent")
    plan["status"] = "COMPLETED"
    plan["verification_scan_id"] = verification_scan_id
    plan["actual_completion_at"] = store.now_iso()
    touch(plan)
    finding = store.findings.get(plan["finding_id"])
    if finding:
        finding["remediation_status"] = "VERIFIED"
        touch(finding)
    return success_obj(plan_view(plan))


@bp.route("/oss-products/<productId>/remediation-plans/<planId>/reject", methods=["POST"])
def reject_plan(productId, planId):
    require_roles("EngineeringManager")
    _, plan = _resolve(productId, planId)
    if plan["status"] != "PROPOSED":
        raise err(ERR_PLAN_NOT_PROPOSED, "RemediationPlan must be PROPOSED")
    plan["status"] = "REJECTED"
    touch(plan)
    return success_obj(plan_view(plan))


@bp.route("/oss-products/<productId>/remediation-plans/<planId>/abandon", methods=["POST"])
def abandon_plan(productId, planId):
    require_roles("EngineeringManager")
    _, plan = _resolve(productId, planId)
    if plan["status"] not in ("APPROVED", "IN_PROGRESS"):
        raise err(ERR_PLAN_NOT_ABANDONABLE, "RemediationPlan must be APPROVED or IN_PROGRESS")
    plan["status"] = "ABANDONED"
    touch(plan)
    finding = store.findings.get(plan["finding_id"])
    if finding:
        finding["remediation_status"] = "NOT_STARTED"
        touch(finding)
    return success_obj(plan_view(plan))
