"""CorrectiveActionPlan endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_FINDING_NOT_OPEN,
    ERR_CAP_ALREADY_OPEN,
    ERR_CAP_INVALID_STATE,
    ERR_VERIFICATION_AUDITOR_CONFLICT,
)
from services.utils import new_uuid
from services.scorecard import (
    recompute_supplier_scorecard,
    find_supplier_for_finding,
)

bp = Blueprint("caps", __name__)

OPEN_CAP_STATUSES = {"SUBMITTED", "APPROVED", "REJECTED", "VERIFICATION_REQUESTED", "VERIFICATION_FAILED"}


def serialize(c):
    return {
        "id": c["id"],
        "finding_id": c["finding_id"],
        "supplier_id": c["supplier_id"],
        "actions": c["actions"],
        "status": c["status"],
        "rejection_reason": c.get("rejection_reason"),
        "escalation_count": c["escalation_count"],
        "verified_by_auditor_id": c.get("verified_by_auditor_id"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _validate_actions(actions):
    if not isinstance(actions, list) or len(actions) < 1:
        return False
    for item in actions:
        if not isinstance(item, dict):
            return False
        if not isinstance(item.get("description"), str):
            return False
        if not isinstance(item.get("owner"), str):
            return False
        if not isinstance(item.get("due_date"), str):
            return False
    return True


@bp.route("/corrective-action-plans", methods=["POST"])
def create_cap():
    user_id, _ = require_roles("SupplierContact")
    body = request.get_json(silent=True) or {}
    finding_id = body.get("finding_id")
    actions = body.get("actions")
    if not isinstance(finding_id, str) or not finding_id:
        raise_err(ERR_INVALID_REQUEST, "finding_id is required")
    if not _validate_actions(actions):
        raise_err(ERR_INVALID_REQUEST,
                  "actions must be a non-empty array of {description, owner, due_date}")
    finding = db.findings.get(finding_id)
    if not finding:
        raise_err(ERR_NOT_FOUND, "finding not found")
    # Existence done; now derive chain
    supplier, audit, facility = find_supplier_for_finding(finding)
    # Ownership: caller's X-User-ID must equal supplier_id
    if supplier is None:
        raise_err(ERR_NOT_FOUND, "supplier not found for finding")
    if user_id != supplier["id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller does not own the supplier chain")
    # State: finding OPEN
    if finding["status"] != "OPEN":
        raise_err(ERR_FINDING_NOT_OPEN, f"finding status is {finding['status']}")
    # Uniqueness: one open CAP per finding
    for c in db.caps.values():
        if c["finding_id"] == finding_id and c["status"] in OPEN_CAP_STATUSES:
            raise_err(ERR_CAP_ALREADY_OPEN, "an open CAP already exists for this finding")
    cap = {
        "id": new_uuid(),
        "finding_id": finding_id,
        "supplier_id": supplier["id"],
        "actions": list(actions),
        "status": "SUBMITTED",
        "rejection_reason": None,
        "escalation_count": 0,
        "verified_by_auditor_id": None,
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.caps[cap["id"]] = cap
    return success_object(serialize(cap), 201)


@bp.route("/corrective-action-plans", methods=["GET"])
def list_caps():
    require_roles(*ALL_BUSINESS_ROLES)
    limit, offset = get_pagination()
    fid = request.args.get("finding_id")
    sid = request.args.get("supplier_id")
    status_f = request.args.get("status")
    items = list(db.caps.values())
    if fid is not None:
        items = [c for c in items if c["finding_id"] == fid]
    if sid is not None:
        items = [c for c in items if c["supplier_id"] == sid]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(c) for c in page], total, limit, offset)


@bp.route("/corrective-action-plans/<cid>", methods=["GET"])
def get_cap(cid):
    require_roles(*ALL_BUSINESS_ROLES)
    c = db.caps.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "CAP not found")
    return success_object(serialize(c))


@bp.route("/corrective-action-plans/<cid>/review", methods=["POST"])
def review_cap(cid):
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    rejection_reason = body.get("rejection_reason")
    if decision not in ("APPROVE", "REJECT"):
        raise_err(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")
    c = db.caps.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "CAP not found")
    if c["status"] != "SUBMITTED":
        raise_err(ERR_CAP_INVALID_STATE, f"CAP status is {c['status']}")
    if decision == "APPROVE":
        c["status"] = "APPROVED"
    else:
        if not isinstance(rejection_reason, str) or not rejection_reason:
            raise_err(ERR_INVALID_REQUEST, "rejection_reason is required for REJECT")
        c["status"] = "REJECTED"
        c["rejection_reason"] = rejection_reason
    c["version"] += 1
    c["updated_at"] = db.get_clock()
    return success_object(serialize(c))


@bp.route("/corrective-action-plans/<cid>/resubmit", methods=["POST"])
def resubmit_cap(cid):
    user_id, _ = require_roles("SupplierContact")
    body = request.get_json(silent=True) or {}
    actions = body.get("actions")
    if not _validate_actions(actions):
        raise_err(ERR_INVALID_REQUEST, "actions must be a non-empty array")
    c = db.caps.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "CAP not found")
    if c["status"] != "REJECTED":
        raise_err(ERR_CAP_INVALID_STATE, f"CAP status is {c['status']}")
    if user_id != c["supplier_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller does not own the CAP's supplier")
    c["actions"] = list(actions)
    c["status"] = "SUBMITTED"
    c["version"] += 1
    c["updated_at"] = db.get_clock()
    return success_object(serialize(c))


@bp.route("/corrective-action-plans/<cid>/request-verification", methods=["POST"])
def request_verification(cid):
    user_id, _ = require_roles("SupplierContact")
    c = db.caps.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "CAP not found")
    if c["status"] not in ("APPROVED", "VERIFICATION_FAILED"):
        raise_err(ERR_CAP_INVALID_STATE, f"CAP status is {c['status']}")
    if user_id != c["supplier_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller does not own the CAP's supplier")
    c["status"] = "VERIFICATION_REQUESTED"
    c["version"] += 1
    c["updated_at"] = db.get_clock()
    return success_object(serialize(c))


@bp.route("/corrective-action-plans/<cid>/verify", methods=["POST"])
def verify_cap(cid):
    user_id, _ = require_roles("Auditor")
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    verification_note = body.get("verification_note")
    if outcome not in ("PASS", "FAIL"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be PASS or FAIL")
    c = db.caps.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "CAP not found")
    if c["status"] != "VERIFICATION_REQUESTED":
        raise_err(ERR_CAP_INVALID_STATE, f"CAP status is {c['status']}")
    # Segregation of duties: X-User-ID must identify an ACTIVE auditor different
    # from the originating audit's lead auditor_id.
    verifying_auditor = db.auditors.get(user_id)
    if verifying_auditor is None or verifying_auditor["status"] != "ACTIVE":
        raise_err(ERR_VERIFICATION_AUDITOR_CONFLICT,
                  "verifying auditor must be an ACTIVE auditor")
    # Find originating audit
    finding = db.findings.get(c["finding_id"])
    if not finding:
        raise_err(ERR_NOT_FOUND, "finding not found")
    audit = db.audits.get(finding["audit_id"])
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    if user_id == audit["auditor_id"]:
        raise_err(ERR_VERIFICATION_AUDITOR_CONFLICT,
                  "verifying auditor must differ from audit's lead auditor")

    c["verified_by_auditor_id"] = user_id
    if outcome == "PASS":
        c["status"] = "VERIFIED_PASSED"
        # Finding -> VERIFIED_CLOSED
        finding["status"] = "VERIFIED_CLOSED"
        finding["version"] += 1
        finding["updated_at"] = db.get_clock()
        # Scorecard recompute + supplier recovery check
        supplier, _a, _f = find_supplier_for_finding(finding)
        if supplier is not None:
            recompute_supplier_scorecard(supplier)
    else:  # FAIL
        c["status"] = "VERIFICATION_FAILED"
        c["escalation_count"] += 1
        supplier, _a, _f = find_supplier_for_finding(finding)
        if supplier is not None and c["escalation_count"] >= 2:
            supplier["escalation_penalty_points"] += 5
        if supplier is not None:
            recompute_supplier_scorecard(supplier)
    c["version"] += 1
    c["updated_at"] = db.get_clock()
    return success_object(serialize(c))
