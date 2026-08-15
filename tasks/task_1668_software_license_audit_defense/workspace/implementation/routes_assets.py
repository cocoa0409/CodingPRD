"""Routes: entitlements, deployments, license positions."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_PRODUCT_NOT_FOUND, ERR_ENTITLEMENT_NOT_FOUND,
    ERR_DEPLOYMENT_NOT_FOUND, ERR_LICENSE_POSITION_NOT_FOUND,
    ERR_ENTITLEMENT_INVALID_STATE, ERR_DEPLOYMENT_INVALID_STATE,
    ERR_MEASUREMENT_DATE_IN_FUTURE, ERR_ENTITLEMENT_WINDOW_OVERLAP,
)
from middleware import require_role, INTERNAL_ROLES
from response import success_object, success_list, paginate
from validation import (
    body, req_string, req_positive_int, req_enum, req_datetime, opt_string,
)

bp = Blueprint("assets", __name__)

COVERAGE_CLASSES = ("PRODUCTION", "NON_PRODUCTION", "DISASTER_RECOVERY")
ENTITLEMENT_SOURCES = ("MANUAL_IMPORT", "CONTRACT_EXTRACT", "AUTO_TRUE_UP")
ENVIRONMENTS = ("PRODUCTION", "NON_PRODUCTION")
MEASUREMENT_METHODS = ("SCAN", "MANUAL_DECLARATION")


def _get_product(pid):
    rec = db.products.get(pid)
    if rec is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    return rec


# ---------------------------------------------------------------------------
# Entitlements (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/sam/entitlements")
def create_entitlement():
    require_role(["SAMManager", "ProcurementLead"])
    data = body()
    product_id = req_string(data, "product_id")
    po_number = req_string(data, "purchase_order_number")
    quantity = req_positive_int(data, "quantity")
    coverage_class = req_enum(data, "coverage_class", COVERAGE_CLASSES)
    effective_from = req_datetime(data, "effective_from")
    effective_to = req_datetime(data, "effective_to", required=False)
    source = req_enum(data, "source", ENTITLEMENT_SOURCES)
    if source == "AUTO_TRUE_UP":
        raise_err(ERR_INVALID_REQUEST,
                  "source AUTO_TRUE_UP is system-reserved")
    if effective_to is not None and \
            db.parse_iso(effective_to) <= db.parse_iso(effective_from):
        raise_err(ERR_INVALID_REQUEST,
                  "effective_to must be later than effective_from")
    product = db.products.get(product_id)
    if product is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "product_id does not exist")
    if svc.entitlement_window_overlap(product_id, coverage_class,
                                      effective_from, effective_to):
        raise_err(ERR_ENTITLEMENT_WINDOW_OVERLAP,
                  "Coverage window overlaps an existing SCHEDULED/ACTIVE "
                  "record for the same product and coverage_class")
    now = db.clock.now()
    status = "SCHEDULED" if db.parse_iso(effective_from) > now else "ACTIVE"
    rec = svc.stamp_new({
        "product_id": product_id,
        "purchase_order_number": po_number,
        "quantity": quantity,
        "coverage_class": coverage_class,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": source,
        "status": status,
    })
    db.entitlements[rec["id"]] = rec
    if status == "ACTIVE":
        svc.cascade_product(product_id)
    return success_object(rec, 201)


@bp.get("/sam/products/<pid>/entitlements")
def list_entitlements(pid):
    require_role(INTERNAL_ROLES)
    _get_product(pid)
    records = [e for e in db.entitlements.values() if e["product_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        records = [e for e in records if e["status"] == status]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/sam/entitlements/<eid>/void")
def void_entitlement(eid):
    require_role(["SAMManager"])
    rec = db.entitlements.get(eid)
    if rec is None:
        raise_err(ERR_ENTITLEMENT_NOT_FOUND, "EntitlementRecord not found")
    if rec["status"] not in ("ACTIVE", "SCHEDULED"):
        raise_err(ERR_ENTITLEMENT_INVALID_STATE,
                  "Only ACTIVE or SCHEDULED entitlements can be voided")
    was_active = rec["status"] == "ACTIVE"
    rec["status"] = "VOID"
    svc.touch(rec)
    if was_active:
        svc.cascade_product(rec["product_id"])
    return success_object(rec)


# ---------------------------------------------------------------------------
# Deployments (PRD §3.3)
# ---------------------------------------------------------------------------

@bp.post("/sam/deployments")
def create_deployment():
    require_role(["ITAnalyst"])
    data = body()
    product_id = req_string(data, "product_id")
    quantity = req_positive_int(data, "measured_quantity")
    environment = req_enum(data, "environment", ENVIRONMENTS)
    method = req_enum(data, "measurement_method", MEASUREMENT_METHODS)
    measured_on = req_datetime(data, "measured_on")
    product = db.products.get(product_id)
    if product is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "product_id does not exist")
    rec = svc.stamp_new({
        "product_id": product_id,
        "measured_quantity": quantity,
        "environment": environment,
        "measurement_method": method,
        "measured_on": measured_on,
        "status": "REPORTED",
        "excluded_by_remediation_id": None,
        "rejection_reason": None,
    })
    db.deployments[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/sam/products/<pid>/deployments")
def list_deployments(pid):
    require_role(INTERNAL_ROLES)
    _get_product(pid)
    records = [d for d in db.deployments.values() if d["product_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        records = [d for d in records if d["status"] == status]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/sam/deployments/<did>/confirm")
def confirm_deployment(did):
    require_role(["SAMManager"])
    rec = db.deployments.get(did)
    if rec is None:
        raise_err(ERR_DEPLOYMENT_NOT_FOUND, "DeploymentRecord not found")
    if rec["status"] != "REPORTED":
        raise_err(ERR_DEPLOYMENT_INVALID_STATE,
                  "Only REPORTED deployments can be confirmed")
    if db.parse_iso(rec["measured_on"]) > db.clock.now():
        raise_err(ERR_MEASUREMENT_DATE_IN_FUTURE,
                  "measured_on is later than the current clock")
    rec["status"] = "CONFIRMED"
    svc.touch(rec)
    svc.cascade_product(rec["product_id"])
    return success_object(rec)


@bp.post("/sam/deployments/<did>/reject")
def reject_deployment(did):
    require_role(["SAMManager"])
    data = body()
    reason = opt_string(data, "rejection_reason")
    rec = db.deployments.get(did)
    if rec is None:
        raise_err(ERR_DEPLOYMENT_NOT_FOUND, "DeploymentRecord not found")
    if rec["status"] != "REPORTED":
        raise_err(ERR_DEPLOYMENT_INVALID_STATE,
                  "Only REPORTED deployments can be rejected")
    rec["status"] = "REJECTED"
    if reason is not None:
        rec["rejection_reason"] = reason
    svc.touch(rec)
    return success_object(rec)


# ---------------------------------------------------------------------------
# License positions (PRD §3.4)
# ---------------------------------------------------------------------------

@bp.get("/sam/products/<pid>/license-positions")
def get_product_position(pid):
    require_role(INTERNAL_ROLES)
    _get_product(pid)
    pos = svc.position_for_product(pid)
    records = [pos] if pos is not None else []
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/sam/license-positions/<pid>/recalculate")
def recalculate_position(pid):
    require_role(["SAMManager"])
    pos = db.positions.get(pid)
    if pos is None:
        raise_err(ERR_LICENSE_POSITION_NOT_FOUND, "LicensePosition not found")
    svc.recompute_position(pos)
    for case in svc.non_terminal_cases_scoping(pos["product_id"]):
        svc.recompute_case_rollups(case)
    svc.upsert_alerts(pos["product_id"])
    return success_object(pos)
