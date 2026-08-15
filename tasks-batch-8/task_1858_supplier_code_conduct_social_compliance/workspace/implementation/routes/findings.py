"""Finding endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_AUDIT_INVALID_STATE,
    ERR_ZT_CATEGORY_NOT_RECOGNIZED,
    ERR_FINDING_NOT_OPEN,
)
from services.utils import new_uuid, parse_iso, to_iso_ms, add_days
from services.scorecard import (
    recompute_audit_tallies,
    recompute_supplier_scorecard,
    recompute_facility_risk,
    find_supplier_for_audit,
    DUE_DAYS,
)

bp = Blueprint("findings", __name__)

CLASSIFICATIONS = {"ZERO_TOLERANCE", "MAJOR", "MINOR"}
CATEGORIES = {"FORCED_LABOR", "CHILD_LABOR", "WORKING_HOURS", "WAGES",
              "HEALTH_SAFETY", "ENVIRONMENT", "HARASSMENT", "RECRUITMENT_FEES"}


def serialize(f):
    return {
        "id": f["id"],
        "audit_id": f["audit_id"],
        "classification": f["classification"],
        "category": f["category"],
        "description": f["description"],
        "status": f["status"],
        "remediation_due_date": f["remediation_due_date"],
        "void_justification": f.get("void_justification"),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


@bp.route("/audits/<audit_id>/findings", methods=["POST"])
def create_finding(audit_id):
    user_id, _ = require_roles("Auditor")
    body = request.get_json(silent=True) or {}
    classification = body.get("classification")
    category = body.get("category")
    description = body.get("description")
    if classification not in CLASSIFICATIONS:
        raise_err(ERR_INVALID_REQUEST, f"classification must be one of {sorted(CLASSIFICATIONS)}")
    if category not in CATEGORIES:
        raise_err(ERR_INVALID_REQUEST, f"category must be one of {sorted(CATEGORIES)}")
    if not isinstance(description, str) or not description:
        raise_err(ERR_INVALID_REQUEST, "description is required")
    audit = db.audits.get(audit_id)
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    # State: audit must be IN_PROGRESS
    if audit["status"] != "IN_PROGRESS":
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {audit['status']}")
    # Ownership
    if user_id != audit["auditor_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller is not the audit's lead auditor")
    # ZT category recognition
    supplier, facility = find_supplier_for_audit(audit)
    if classification == "ZERO_TOLERANCE":
        cv_id = supplier["current_code_version_id"] if supplier else None
        cv = db.code_versions.get(cv_id) if cv_id else None
        zt_cats = set(cv["zero_tolerance_categories"]) if cv else set()
        if category not in zt_cats:
            raise_err(ERR_ZT_CATEGORY_NOT_RECOGNIZED,
                      f"category {category} not in supplier's current code version zero_tolerance_categories")

    # Create finding
    now = db.get_clock()
    now_dt = parse_iso(now)
    due_days = DUE_DAYS[classification]
    remediation_due = to_iso_ms(add_days(now_dt, due_days))
    f = {
        "id": new_uuid(),
        "audit_id": audit_id,
        "classification": classification,
        "category": category,
        "description": description,
        "status": "OPEN",
        "remediation_due_date": remediation_due,
        "void_justification": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.findings[f["id"]] = f

    # Audit tallies recompute
    recompute_audit_tallies(audit)

    # ZT cascade
    if classification == "ZERO_TOLERANCE":
        # Audit IN_PROGRESS -> FAILED_ZT
        audit["status"] = "FAILED_ZT"
        audit["version"] += 1
        audit["updated_at"] = db.get_clock()
        # Facility risk recompute (FAILED_ZT is terminal)
        if facility is not None:
            recompute_facility_risk(facility)

    # Supplier scorecard recompute (covers PROBATION gating)
    if supplier is not None:
        recompute_supplier_scorecard(supplier)

    return success_object(serialize(f), 201)


@bp.route("/audits/<audit_id>/findings", methods=["GET"])
def list_findings(audit_id):
    require_roles(*ALL_BUSINESS_ROLES)
    audit = db.audits.get(audit_id)
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    limit, offset = get_pagination()
    cls_f = request.args.get("classification")
    status_f = request.args.get("status")
    items = [f for f in db.findings.values() if f["audit_id"] == audit_id]
    if cls_f is not None:
        items = [f for f in items if f["classification"] == cls_f]
    if status_f is not None:
        items = [f for f in items if f["status"] == status_f]
    items.sort(key=lambda f: f["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(f) for f in page], total, limit, offset)


@bp.route("/findings/<fid>", methods=["GET"])
def get_finding(fid):
    require_roles(*ALL_BUSINESS_ROLES)
    f = db.findings.get(fid)
    if not f:
        raise_err(ERR_NOT_FOUND, "finding not found")
    return success_object(serialize(f))


@bp.route("/findings/<fid>/void", methods=["POST"])
def void_finding(fid):
    user_id, _ = require_roles("Auditor")
    body = request.get_json(silent=True) or {}
    void_justification = body.get("void_justification")
    if not isinstance(void_justification, str) or len(void_justification) < 10:
        raise_err(ERR_INVALID_REQUEST, "void_justification must be at least 10 characters")
    f = db.findings.get(fid)
    if not f:
        raise_err(ERR_NOT_FOUND, "finding not found")
    # State: finding OPEN first
    if f["status"] != "OPEN":
        raise_err(ERR_FINDING_NOT_OPEN, f"finding status is {f['status']}")
    # Audit state
    audit = db.audits.get(f["audit_id"])
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    if audit["status"] not in ("IN_PROGRESS", "REPORT_SUBMITTED", "FAILED_ZT"):
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {audit['status']}")
    # Ownership
    if user_id != audit["auditor_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller is not the audit's lead auditor")
    f["status"] = "VOIDED"
    f["void_justification"] = void_justification
    f["version"] += 1
    f["updated_at"] = db.get_clock()
    # Side effects
    recompute_audit_tallies(audit)
    supplier, facility = find_supplier_for_audit(audit)
    if supplier is not None:
        recompute_supplier_scorecard(supplier)
    if audit["status"] in ("COMPLETED", "FAILED_ZT") and facility is not None:
        recompute_facility_risk(facility)
    return success_object(serialize(f))
