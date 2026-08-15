"""Supplier endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_SUPPLIER_ALREADY_TERMINATED,
)
from services.utils import new_uuid
from services.scorecard import (
    recompute_audit_tallies,
)

bp = Blueprint("suppliers", __name__)

SECTORS = {"APPAREL", "ELECTRONICS", "FOOD", "HARDLINES"}


def serialize(s):
    return {
        "id": s["id"],
        "legal_name": s["legal_name"],
        "country_code": s["country_code"],
        "sector": s["sector"],
        "status": s["status"],
        "current_code_version_id": s["current_code_version_id"],
        "provisional_score": s["provisional_score"],
        "verified_score": s["verified_score"],
        "consequence_tier": s["consequence_tier"],
        "escalation_penalty_points": s["escalation_penalty_points"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/suppliers", methods=["POST"])
def create_supplier():
    require_roles("SourcingProgramAdmin")
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    country_code = body.get("country_code")
    sector = body.get("sector")
    if not isinstance(legal_name, str) or not legal_name:
        raise_err(ERR_INVALID_REQUEST, "legal_name is required")
    if not isinstance(country_code, str) or not country_code:
        raise_err(ERR_INVALID_REQUEST, "country_code is required")
    if sector not in SECTORS:
        raise_err(ERR_INVALID_REQUEST, f"sector must be one of {sorted(SECTORS)}")
    s = {
        "id": new_uuid(),
        "legal_name": legal_name,
        "country_code": country_code,
        "sector": sector,
        "status": "ONBOARDING",
        "current_code_version_id": None,
        "provisional_score": 100,
        "verified_score": 100,
        "consequence_tier": "PREFERRED",
        "escalation_penalty_points": 0,
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.suppliers[s["id"]] = s
    return success_object(serialize(s), 201)


@bp.route("/suppliers", methods=["GET"])
def list_suppliers():
    require_roles(*ALL_BUSINESS_ROLES)
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    tier_f = request.args.get("consequence_tier")
    ccv_f = request.args.get("current_code_version_id")
    items = list(db.suppliers.values())
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    if tier_f is not None:
        items = [s for s in items if s["consequence_tier"] == tier_f]
    if ccv_f is not None:
        items = [s for s in items if s["current_code_version_id"] == ccv_f]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(s) for s in page], total, limit, offset)


@bp.route("/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    require_roles(*ALL_BUSINESS_ROLES)
    s = db.suppliers.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, "supplier not found")
    return success_object(serialize(s))


@bp.route("/suppliers/<sid>/scorecard", methods=["GET"])
def get_scorecard(sid):
    require_roles(*ALL_BUSINESS_ROLES)
    s = db.suppliers.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, "supplier not found")
    # Compute live counts
    fac_ids = {f["id"] for f in db.facilities.values() if f["supplier_id"] == sid}
    audit_ids = {a["id"] for a in db.audits.values() if a["facility_id"] in fac_ids}
    open_zt = open_major = open_minor = 0
    for f in db.findings.values():
        if f["audit_id"] in audit_ids and f["status"] == "OPEN":
            if f["classification"] == "ZERO_TOLERANCE":
                open_zt += 1
            elif f["classification"] == "MAJOR":
                open_major += 1
            elif f["classification"] == "MINOR":
                open_minor += 1
    unresolved_crit = sum(
        1 for g in db.grievances.values()
        if g["facility_id"] in fac_ids
        and g["severity"] == "CRITICAL"
        and g["status"] in ("SUBMITTED", "UNDER_REVIEW", "ESCALATED")
    )
    return success_object({
        "supplier_id": sid,
        "provisional_score": s["provisional_score"],
        "verified_score": s["verified_score"],
        "consequence_tier": s["consequence_tier"],
        "escalation_penalty_points": s["escalation_penalty_points"],
        "open_zt_count": open_zt,
        "open_major_count": open_major,
        "open_minor_count": open_minor,
        "unresolved_critical_grievance_count": unresolved_crit,
    })


@bp.route("/suppliers/<sid>/terminate", methods=["POST"])
def terminate_supplier(sid):
    require_roles("ComplianceOfficer")
    s = db.suppliers.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, "supplier not found")
    if s["status"] not in ("ACTIVE", "PROBATION"):
        raise_err(ERR_SUPPLIER_ALREADY_TERMINATED,
                  f"supplier status is {s['status']}")
    s["status"] = "TERMINATED"
    s["version"] += 1
    s["updated_at"] = db.get_clock()
    # Cascade facilities to EXITED
    for fac in db.facilities.values():
        if fac["supplier_id"] == sid and fac["status"] == "ACTIVE":
            fac["status"] = "EXITED"
            fac["version"] += 1
            fac["updated_at"] = db.get_clock()
    # Cascade audits of those facilities in {SCHEDULED, IN_PROGRESS, REPORT_SUBMITTED} -> CANCELLED
    fac_ids = {f["id"] for f in db.facilities.values() if f["supplier_id"] == sid}
    for a in db.audits.values():
        if a["facility_id"] in fac_ids and a["status"] in ("SCHEDULED", "IN_PROGRESS", "REPORT_SUBMITTED"):
            a["status"] = "CANCELLED"
            a["version"] += 1
            a["updated_at"] = db.get_clock()
    return success_object(serialize(s))
