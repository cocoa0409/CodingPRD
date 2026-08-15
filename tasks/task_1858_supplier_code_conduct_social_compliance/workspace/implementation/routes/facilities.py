"""Facility endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_SUPPLIER_ALREADY_TERMINATED,
    ERR_AUDIT_ALREADY_OPEN,
    ERR_OUTSTANDING_REIMBURSEMENT,
)
from services.utils import new_uuid
from services.scorecard import (
    compute_baseline_risk,
    derive_risk_tier,
    TIER_BASE_MONTHS,
)

bp = Blueprint("facilities", __name__)


def serialize(f):
    return {
        "id": f["id"],
        "supplier_id": f["supplier_id"],
        "name": f["name"],
        "country_code": f["country_code"],
        "worker_count": f["worker_count"],
        "processes": f["processes"],
        "status": f["status"],
        "risk_score_baseline": f["risk_score_baseline"],
        "risk_score_history": f["risk_score_history"],
        "risk_tier": f["risk_tier"],
        "next_audit_interval_months": f["next_audit_interval_months"],
        "next_audit_due_date": f["next_audit_due_date"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


@bp.route("/facilities", methods=["POST"])
def create_facility():
    require_roles("SourcingProgramAdmin")
    body = request.get_json(silent=True) or {}
    supplier_id = body.get("supplier_id")
    name = body.get("name")
    country_code = body.get("country_code")
    worker_count = body.get("worker_count")
    processes = body.get("processes")
    if not isinstance(supplier_id, str) or not supplier_id:
        raise_err(ERR_INVALID_REQUEST, "supplier_id is required")
    if not isinstance(name, str) or not name:
        raise_err(ERR_INVALID_REQUEST, "name is required")
    if not isinstance(country_code, str) or not country_code:
        raise_err(ERR_INVALID_REQUEST, "country_code is required")
    if not isinstance(worker_count, int) or isinstance(worker_count, bool) or worker_count < 1:
        raise_err(ERR_INVALID_REQUEST, "worker_count must be an integer >= 1")
    if not isinstance(processes, list):
        raise_err(ERR_INVALID_REQUEST, "processes must be an array")
    supplier = db.suppliers.get(supplier_id)
    if not supplier:
        raise_err(ERR_NOT_FOUND, "supplier not found")
    if supplier["status"] == "TERMINATED":
        raise_err(ERR_SUPPLIER_ALREADY_TERMINATED, "supplier is TERMINATED")
    fac = {
        "id": new_uuid(),
        "supplier_id": supplier_id,
        "name": name,
        "country_code": country_code,
        "worker_count": worker_count,
        "processes": list(processes),
        "status": "ACTIVE",
        "risk_score_baseline": 0.0,
        "risk_score_history": None,
        "risk_tier": "LOW",
        "next_audit_interval_months": 0,
        "next_audit_due_date": None,
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    fac["risk_score_baseline"] = compute_baseline_risk(supplier, fac)
    fac["risk_tier"] = derive_risk_tier(fac)
    fac["next_audit_interval_months"] = TIER_BASE_MONTHS[fac["risk_tier"]]
    fac["next_audit_due_date"] = None
    db.facilities[fac["id"]] = fac
    return success_object(serialize(fac), 201)


@bp.route("/facilities", methods=["GET"])
def list_facilities():
    require_roles(*ALL_BUSINESS_ROLES)
    limit, offset = get_pagination()
    sid = request.args.get("supplier_id")
    status_f = request.args.get("status")
    tier_f = request.args.get("risk_tier")
    items = list(db.facilities.values())
    if sid is not None:
        items = [f for f in items if f["supplier_id"] == sid]
    if status_f is not None:
        items = [f for f in items if f["status"] == status_f]
    if tier_f is not None:
        items = [f for f in items if f["risk_tier"] == tier_f]
    items.sort(key=lambda f: f["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(f) for f in page], total, limit, offset)


@bp.route("/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    require_roles(*ALL_BUSINESS_ROLES)
    f = db.facilities.get(fid)
    if not f:
        raise_err(ERR_NOT_FOUND, "facility not found")
    return success_object(serialize(f))


@bp.route("/facilities/<fid>/scoping", methods=["GET"])
def get_facility_scoping(fid):
    require_roles(*ALL_BUSINESS_ROLES)
    f = db.facilities.get(fid)
    if not f:
        raise_err(ERR_NOT_FOUND, "facility not found")
    return success_object(serialize(f))


@bp.route("/facilities/<fid>/exit", methods=["POST"])
def exit_facility(fid):
    require_roles("SourcingProgramAdmin")
    f = db.facilities.get(fid)
    if not f:
        raise_err(ERR_NOT_FOUND, "facility not found")
    if f["status"] != "ACTIVE":
        # Already exited
        raise_err(ERR_AUDIT_ALREADY_OPEN, "facility is not ACTIVE")
    # Check open audits
    for a in db.audits.values():
        if a["facility_id"] == fid and a["status"] in ("SCHEDULED", "IN_PROGRESS", "REPORT_SUBMITTED"):
            raise_err(ERR_AUDIT_ALREADY_OPEN, "an open audit exists at the facility")
    # Check outstanding reimbursements on this facility's audits
    audit_ids = {a["id"] for a in db.audits.values() if a["facility_id"] == fid}
    for r in db.recruitment_fee_reviews.values():
        if r["audit_id"] in audit_ids and r["status"] == "VIOLATION_CONFIRMED" and r["outstanding_reimbursement_cents"] > 0:
            raise_err(ERR_OUTSTANDING_REIMBURSEMENT,
                      "outstanding reimbursement blocks facility exit")
    f["status"] = "EXITED"
    f["version"] += 1
    f["updated_at"] = db.get_clock()
    return success_object(serialize(f))
