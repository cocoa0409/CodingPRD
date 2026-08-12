"""Quality audit endpoints (PRD 3.7): for-cause creation, verdict recording,
FAIL cascade with contractor score recompute and auto-suspension."""
import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import (
    get_or_404,
    list_page,
    recompute_contractor_score,
    ser_audit,
)
from flask import Blueprint, request
from validate import body, req_enum, req_int, req_str

bp = Blueprint("audits", __name__)

AUDIT_TYPES = ("SAMPLED", "FOR_CAUSE")


@bp.post("/api/quality-audits")
@require_roles("QualityAuditor")
def create_audit():
    b = body()
    work_order_id = b.get("work_order_id")
    if isinstance(work_order_id, str):
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    work_order_id = req_str(b, "work_order_id")
    wo = get_or_404(db.work_orders, work_order_id, "WorkOrder")
    audit_type = req_enum(b, "audit_type", AUDIT_TYPES)
    # SAMPLED audits are the auto-created ones; manual raises use FOR_CAUSE.
    if audit_type == "SAMPLED":
        raise_err("ERR_VALIDATION",
                  "SAMPLED audits are auto-created; use FOR_CAUSE")
    if wo["lifecycle_status"] not in ("QA_REVIEW", "QA_FAILED"):
        raise_err("ERR_INVALID_STATE",
                  "Work order must be in QA_REVIEW or QA_FAILED")
    a = base_resource()
    a.update({
        "work_order_id": wo["id"],
        "contractor_id": wo["contractor_id"],
        "audit_type": audit_type,
        "checks_total": None,
        "checks_passed": None,
        "defects_found": None,
        "recorded_at": None,
        "result_status": "PENDING",
    })
    db.quality_audits[a["id"]] = a
    return ok_object(ser_audit(a), 201)


@bp.get("/api/quality-audits")
@require_roles(*ALL_ROLES)
def list_audits():
    filters = {}
    for k in ("work_order_id", "contractor_id", "result_status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.quality_audits.values(), filters, ser_audit)


@bp.get("/api/quality-audits/<auditId>")
@require_roles(*ALL_ROLES)
def get_audit(auditId):
    return ok_object(ser_audit(get_or_404(db.quality_audits, auditId, "QualityAudit")))


@bp.post("/api/quality-audits/<auditId>/record")
@require_roles("QualityAuditor")
def record_audit(auditId):
    a = get_or_404(db.quality_audits, auditId, "QualityAudit")
    b = body()
    checks_total = req_int(b, "checks_total", min=1)
    checks_passed = req_int(b, "checks_passed", min=0)
    defects_found = req_int(b, "defects_found", min=0)
    if a["result_status"] != "PENDING":
        raise_err("ERR_INVALID_STATE", "Audit is not PENDING")
    # PASS iff defects_found == 0 AND checks_passed == checks_total.
    result = "PASS" if (defects_found == 0 and checks_passed == checks_total) else "FAIL"
    a["checks_total"] = checks_total
    a["checks_passed"] = checks_passed
    a["defects_found"] = defects_found
    a["result_status"] = result
    a["recorded_at"] = clock_now()
    touch(a)
    contractor = db.contractors.get(a["contractor_id"])
    if result == "FAIL":
        # Cascade link 1: work order QA_REVIEW -> QA_FAILED.
        wo = db.work_orders.get(a["work_order_id"])
        if wo is not None and wo["lifecycle_status"] == "QA_REVIEW":
            wo["lifecycle_status"] = "QA_FAILED"
            touch(wo)
    if contractor is not None:
        # Cascade link 2/3: score recompute; auto-suspend below 9200.
        recompute_contractor_score(contractor)
    return ok_object(ser_audit(a))
