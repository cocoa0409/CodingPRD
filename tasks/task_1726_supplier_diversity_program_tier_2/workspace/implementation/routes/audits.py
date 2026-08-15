"""Data-quality audit cases and the revocation cascade (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AUDIT_ALREADY_OPEN,
    ERR_CERT_NOT_SELF_CERT,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import (
    make_record,
    touch,
    pub_audit_case,
    refresh_diverse_eligible,
    refresh_risk_scores,
    recompute_events_for_supplier,
    suspend_supplier_cascade,
)
from util import now
from validate import get_body, req_str, get_resource

bp = Blueprint("audits", __name__)

AUDITOR = ["Auditor"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "Auditor"]


@bp.route("/api/v1/audit-cases", methods=["POST"])
def create_audit_case():
    caller = authorized(AUDITOR)
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    certification_id = req_str(body, "certification_id")
    reason = req_str(body, "reason")
    supplier = get_resource("suppliers", supplier_id)
    cert = get_resource("certifications", certification_id)
    if cert["supplier_id"] != supplier["id"]:
        raise_error(ERR_NOT_FOUND, "certification does not belong to the supplier")
    # State rung: the target certification must currently be VERIFIED.
    if cert["status"] != "VERIFIED":
        raise_error(ERR_INVALID_STATE, "audit target certification must be VERIFIED")
    # Segregation/eligibility rung.
    if cert["cert_type"] != "SELF_CERT":
        raise_error(ERR_CERT_NOT_SELF_CERT, "audit target must be a SELF_CERT certification")
    if cert["verified_by_user_id"] == caller.user_id:
        raise_error(ERR_SOD_VIOLATION, "auditor may not audit a certification they verified")
    # Uniqueness rung: at most one OPEN audit per certification.
    for case in db["audit_cases"].values():
        if case["certification_id"] == cert["id"] and case["status"] == "OPEN":
            raise_error(ERR_AUDIT_ALREADY_OPEN, "an OPEN audit already exists for the certification")
    rec = make_record({
        "supplier_id": supplier["id"],
        "certification_id": cert["id"],
        "reason": reason,
        "auditor_user_id": caller.user_id,
        "outcome": None,
        "outcome_recorded_at": None,
        "status": "OPEN",
    })
    db["audit_cases"][rec["id"]] = rec
    # CONSERVATIVE risk variant carries an open-audit term (PRD 3.10).
    if refresh_risk_scores(supplier):
        touch(supplier)
    return success_object(pub_audit_case(rec), status=201)


@bp.route("/api/v1/audit-cases", methods=["GET"])
def list_audit_cases():
    authorized(READERS)
    filters = {
        "supplier_id": request.args.get("supplier_id"),
        "certification_id": request.args.get("certification_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(db["audit_cases"].values()), filters, pub_audit_case)


@bp.route("/api/v1/audit-cases/<rid>", methods=["GET"])
def get_audit_case(rid):
    authorized(READERS)
    rec = get_resource("audit_cases", rid)
    return success_object(pub_audit_case(rec))


@bp.route("/api/v1/audit-cases/<rid>/record-outcome", methods=["POST"])
def record_outcome(rid):
    caller = authorized(AUDITOR)
    case = get_resource("audit_cases", rid)
    # Owning auditor only (PRD 3.9).
    if case["auditor_user_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "only the owning auditor may record the outcome")
    if case["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "record-outcome requires status OPEN")
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("CONFIRMED", "FAILED"):
        raise_error(ERR_INVALID_REQUEST, "outcome must be CONFIRMED or FAILED")
    case["outcome"] = outcome
    case["outcome_recorded_at"] = now()
    case["status"] = outcome
    touch(case)
    supplier = db["suppliers"].get(case["supplier_id"])
    if outcome == "CONFIRMED":
        if supplier is not None and refresh_risk_scores(supplier):
            touch(supplier)
        return success_object(pub_audit_case(case))
    # FAILED: the revocation cascade (PRD 3.9).
    cert = db["certifications"].get(case["certification_id"])
    if cert is not None and cert["status"] == "VERIFIED":
        cert["status"] = "REVOKED"  # the only producer of REVOKED
        touch(cert)
    if supplier is not None:
        suspend_supplier_cascade(supplier)
        if refresh_risk_scores(supplier):
            touch(supplier)
    return success_object(pub_audit_case(case))
