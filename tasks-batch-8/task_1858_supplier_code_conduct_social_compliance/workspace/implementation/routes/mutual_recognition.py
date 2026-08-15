"""MutualRecognitionClaim endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_CLAIM_INVALID_STATE,
    ERR_OPEN_ZT_FINDINGS_EXIST,
    ERR_EXTERNAL_SCORE_TOO_LOW,
    ERR_EXTERNAL_AUDIT_STALE,
)
from services.utils import new_uuid, parse_iso
from services.scorecard import (
    PROGRAM_MIN_SCORE,
    recompute_facility_risk,
    _subtract_months,
)

bp = Blueprint("mutual_recognition", __name__)

PROGRAM_NAMES = {"BSCI", "SMETA", "RBA", "WRAP"}


def serialize(c):
    return {
        "id": c["id"],
        "facility_id": c["facility_id"],
        "program_name": c["program_name"],
        "external_audit_ref": c["external_audit_ref"],
        "external_audit_date": c["external_audit_date"],
        "external_score": c["external_score"],
        "status": c["status"],
        "decision_reason": c.get("decision_reason"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/mutual-recognition-claims", methods=["POST"])
def create_claim():
    user_id, _ = require_roles("SupplierContact")
    body = request.get_json(silent=True) or {}
    facility_id = body.get("facility_id")
    program_name = body.get("program_name")
    external_audit_ref = body.get("external_audit_ref")
    external_audit_date = body.get("external_audit_date")
    external_score = body.get("external_score")
    if not isinstance(facility_id, str) or not facility_id:
        raise_err(ERR_INVALID_REQUEST, "facility_id is required")
    if program_name not in PROGRAM_NAMES:
        raise_err(ERR_INVALID_REQUEST, f"program_name must be one of {sorted(PROGRAM_NAMES)}")
    if not isinstance(external_audit_ref, str) or not external_audit_ref:
        raise_err(ERR_INVALID_REQUEST, "external_audit_ref is required")
    if not isinstance(external_audit_date, str) or not external_audit_date:
        raise_err(ERR_INVALID_REQUEST, "external_audit_date is required")
    if not isinstance(external_score, (int, float)) or isinstance(external_score, bool):
        raise_err(ERR_INVALID_REQUEST, "external_score must be a number")
    facility = db.facilities.get(facility_id)
    if not facility:
        raise_err(ERR_NOT_FOUND, "facility not found")
    # Ownership: caller's X-User-ID == supplier_id of the facility's chain
    if user_id != facility["supplier_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller does not own the facility's supplier chain")
    c = {
        "id": new_uuid(),
        "facility_id": facility_id,
        "program_name": program_name,
        "external_audit_ref": external_audit_ref,
        "external_audit_date": external_audit_date,
        "external_score": external_score,
        "status": "SUBMITTED",
        "decision_reason": None,
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.mutual_recognition_claims[c["id"]] = c
    return success_object(serialize(c), 201)


@bp.route("/mutual-recognition-claims", methods=["GET"])
def list_claims():
    require_roles(*ALL_BUSINESS_ROLES)
    limit, offset = get_pagination()
    fid = request.args.get("facility_id")
    prog = request.args.get("program_name")
    status_f = request.args.get("status")
    items = list(db.mutual_recognition_claims.values())
    if fid is not None:
        items = [c for c in items if c["facility_id"] == fid]
    if prog is not None:
        items = [c for c in items if c["program_name"] == prog]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(c) for c in page], total, limit, offset)


@bp.route("/mutual-recognition-claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_roles(*ALL_BUSINESS_ROLES)
    c = db.mutual_recognition_claims.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "claim not found")
    return success_object(serialize(c))


@bp.route("/mutual-recognition-claims/<cid>/decide", methods=["POST"])
def decide_claim(cid):
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    decision_reason = body.get("decision_reason")
    if decision not in ("ACCEPT", "REJECT"):
        raise_err(ERR_INVALID_REQUEST, "decision must be ACCEPT or REJECT")
    c = db.mutual_recognition_claims.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "claim not found")
    if c["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_INVALID_STATE, f"claim status is {c['status']}")
    if decision == "ACCEPT":
        # No OPEN ZT finding at the claim's facility
        audit_ids_at_fac = {a["id"] for a in db.audits.values() if a["facility_id"] == c["facility_id"]}
        for f in db.findings.values():
            if (f["audit_id"] in audit_ids_at_fac
                    and f["classification"] == "ZERO_TOLERANCE"
                    and f["status"] == "OPEN"):
                raise_err(ERR_OPEN_ZT_FINDINGS_EXIST,
                          "OPEN zero-tolerance finding exists at the facility")
        # Score minimum
        min_score = PROGRAM_MIN_SCORE.get(c["program_name"], 0)
        if c["external_score"] < min_score:
            raise_err(ERR_EXTERNAL_SCORE_TOO_LOW,
                      f"external_score {c['external_score']} < minimum {min_score}")
        # Staleness: external_audit_date within 12 months of logical clock
        now = parse_iso(db.get_clock())
        ext_dt = parse_iso(c["external_audit_date"])
        if ext_dt is None:
            raise_err(ERR_EXTERNAL_AUDIT_STALE, "external_audit_date is invalid")
        cutoff = _subtract_months(now, 12)
        if ext_dt < cutoff:
            raise_err(ERR_EXTERNAL_AUDIT_STALE,
                      "external_audit_date older than 12 months")
        c["status"] = "ACCEPTED"
        # Facility interval/due-date recompute
        facility = db.facilities.get(c["facility_id"])
        if facility is not None:
            recompute_facility_risk(facility)
    else:  # REJECT
        c["status"] = "REJECTED"
        if isinstance(decision_reason, str):
            c["decision_reason"] = decision_reason
    c["version"] += 1
    c["updated_at"] = db.get_clock()
    return success_object(serialize(c))
