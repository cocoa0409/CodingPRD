"""Routes: remediation actions and monitoring alerts (PRD §3.8, §3.9)."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_INVALID_REQUEST, ERR_PRODUCT_NOT_FOUND, ERR_DEPLOYMENT_NOT_FOUND,
    ERR_REMEDIATION_NOT_FOUND, ERR_ALERT_NOT_FOUND,
    ERR_REMEDIATION_INVALID_STATE, ERR_ALERT_INVALID_STATE,
    ERR_REMEDIATION_TARGET_INVALID, ERR_REMEDIATION_EXCEEDS_GAP,
)
from middleware import require_role, INTERNAL_ROLES
from response import success_object, success_list, paginate
from validation import (
    body, req_string, req_positive_int, req_enum, req_str_array, opt_string,
)

bp = Blueprint("remediation", __name__)

ACTION_TYPES = ("UNINSTALL", "PURCHASE_TRUE_UP")


def _get_action(aid):
    rec = db.remediations.get(aid)
    if rec is None:
        raise_err(ERR_REMEDIATION_NOT_FOUND, "RemediationAction not found")
    return rec


# ---------------------------------------------------------------------------
# Remediation actions
# ---------------------------------------------------------------------------

@bp.post("/sam/remediation-actions")
def create_remediation():
    require_role(["SAMManager"])
    data = body()
    product_id = req_string(data, "product_id")
    action_type = req_enum(data, "action_type", ACTION_TYPES)
    targets = None
    quantity = None
    if action_type == "UNINSTALL":
        targets = req_str_array(data, "target_deployment_ids")
        # Any quantity input on an UNINSTALL is ignored; the server computes
        # it from the targeted deployments.
    else:  # PURCHASE_TRUE_UP
        if isinstance(data.get("target_deployment_ids"), list) and \
                len(data["target_deployment_ids"]) > 0:
            raise_err(ERR_INVALID_REQUEST,
                      "target_deployment_ids is forbidden for "
                      "PURCHASE_TRUE_UP")
        quantity = req_positive_int(data, "quantity")
    product = db.products.get(product_id)
    if product is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "product_id does not exist")
    if action_type == "UNINSTALL":
        deps = []
        for tid in targets:
            d = db.deployments.get(tid)
            if d is None:
                raise_err(ERR_DEPLOYMENT_NOT_FOUND,
                          f"target deployment {tid} does not exist")
            deps.append(d)
        for d in deps:
            if d["product_id"] != product_id or d["status"] != "CONFIRMED":
                raise_err(ERR_REMEDIATION_TARGET_INVALID,
                          "UNINSTALL targets must be CONFIRMED deployments "
                          "of the action's product")
        quantity = sum(d["measured_quantity"] for d in deps)
    pos = svc.position_for_product(product_id)
    if quantity > pos["gap_quantity"]:
        raise_err(ERR_REMEDIATION_EXCEEDS_GAP,
                  "Remediation quantity exceeds the product's current "
                  "gap_quantity")
    rec = svc.stamp_new({
        "product_id": product_id,
        "action_type": action_type,
        "quantity": quantity,
        "target_deployment_ids": list(targets) if targets is not None else None,
        "status": "PLANNED",
        "generated_entitlement_id": None,
        "verification_notes": None,
    })
    db.remediations[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/sam/remediation-actions/<aid>")
def get_remediation(aid):
    require_role(INTERNAL_ROLES)
    return success_object(_get_action(aid))


@bp.get("/sam/products/<pid>/remediation-actions")
def list_product_remediations(pid):
    require_role(INTERNAL_ROLES)
    if pid not in db.products:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    records = [a for a in db.remediations.values() if a["product_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.get("/sam/remediation-actions/<aid>/deployments")
def list_remediation_deployments(aid):
    require_role(INTERNAL_ROLES)
    _get_action(aid)
    records = [d for d in db.deployments.values()
               if d["excluded_by_remediation_id"] == aid]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/sam/remediation-actions/<aid>/start")
def start_remediation(aid):
    require_role(["SAMManager"])
    rec = _get_action(aid)
    if rec["status"] != "PLANNED":
        raise_err(ERR_REMEDIATION_INVALID_STATE,
                  "Only a PLANNED remediation can be started")
    rec["status"] = "IN_PROGRESS"
    svc.touch(rec)
    return success_object(rec)


@bp.post("/sam/remediation-actions/<aid>/complete")
def complete_remediation(aid):
    require_role(["SAMManager"])
    rec = _get_action(aid)
    if rec["status"] != "IN_PROGRESS":
        raise_err(ERR_REMEDIATION_INVALID_STATE,
                  "Only an IN_PROGRESS remediation can be completed")
    if rec["action_type"] == "UNINSTALL":
        for tid in rec["target_deployment_ids"]:
            d = db.deployments.get(tid)
            if d is not None and d["status"] == "CONFIRMED":
                d["status"] = "EXCLUDED"
                d["excluded_by_remediation_id"] = rec["id"]
                svc.touch(d)
    else:  # PURCHASE_TRUE_UP — mint the AUTO_TRUE_UP entitlement
        ent = svc.stamp_new({
            "product_id": rec["product_id"],
            "purchase_order_number": "TRUEUP-" + rec["id"],
            "quantity": rec["quantity"],
            "coverage_class": "PRODUCTION",
            "effective_from": db.now_iso(),
            "effective_to": None,
            "source": "AUTO_TRUE_UP",
            # effective_from == current clock => immediately ACTIVE
            "status": "ACTIVE",
        })
        db.entitlements[ent["id"]] = ent
        rec["generated_entitlement_id"] = ent["id"]
    rec["status"] = "COMPLETED"
    svc.touch(rec)
    # Completion is one of the enumerated cascades that also advance each
    # affected AuditCase's version by exactly one (PRD §2.8).
    svc.cascade_product(rec["product_id"], bump_cases=True)
    return success_object(rec)


@bp.post("/sam/remediation-actions/<aid>/cancel")
def cancel_remediation(aid):
    require_role(["SAMManager"])
    rec = _get_action(aid)
    if rec["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise_err(ERR_REMEDIATION_INVALID_STATE,
                  "Only a PLANNED or IN_PROGRESS remediation can be "
                  "cancelled")
    rec["status"] = "CANCELLED"
    svc.touch(rec)
    return success_object(rec)


@bp.post("/sam/remediation-actions/<aid>/fail-verification")
def fail_verification_remediation(aid):
    require_role(["SAMManager"])
    data = body()
    notes = opt_string(data, "verification_notes")
    rec = _get_action(aid)
    if rec["status"] != "COMPLETED":
        raise_err(ERR_REMEDIATION_INVALID_STATE,
                  "Only a COMPLETED remediation can fail verification")
    # Compensating transaction: reverse every completion effect.
    if rec["action_type"] == "UNINSTALL":
        for d in db.deployments.values():
            if d["excluded_by_remediation_id"] == rec["id"]:
                d["status"] = "CONFIRMED"
                d["excluded_by_remediation_id"] = None
                svc.touch(d)
    else:
        ent = db.entitlements.get(rec["generated_entitlement_id"])
        if ent is not None and ent["status"] in ("ACTIVE", "SCHEDULED"):
            ent["status"] = "VOID"
            svc.touch(ent)
    rec["status"] = "PLANNED"
    if notes is not None:
        rec["verification_notes"] = notes
    svc.touch(rec)
    # Position/rollups/alerts recompute; fail-verification is not among the
    # enumerated case-version-bumping cascades (PRD §2.8).
    svc.cascade_product(rec["product_id"])
    return success_object(rec)


# ---------------------------------------------------------------------------
# Monitoring alerts
# ---------------------------------------------------------------------------

@bp.get("/sam/products/<pid>/monitoring-alerts")
def list_product_alerts(pid):
    require_role(INTERNAL_ROLES)
    if pid not in db.products:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    records = [a for a in db.alerts.values() if a["product_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    alert_type = request.args.get("alert_type")
    if alert_type is not None:
        records = [a for a in records if a["alert_type"] == alert_type]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/sam/monitoring-alerts/<aid>/suppress")
def suppress_alert(aid):
    require_role(["SAMManager"])
    data = body()
    reason = req_string(data, "suppression_reason")
    rec = db.alerts.get(aid)
    if rec is None:
        raise_err(ERR_ALERT_NOT_FOUND, "MonitoringAlert not found")
    if rec["status"] != "OPEN":
        raise_err(ERR_ALERT_INVALID_STATE,
                  "Only an OPEN alert can be suppressed")
    rec["status"] = "SUPPRESSED"
    rec["suppressed_value"] = rec["triggered_value"]
    rec["suppression_reason"] = reason
    svc.touch(rec)
    return success_object(rec)
