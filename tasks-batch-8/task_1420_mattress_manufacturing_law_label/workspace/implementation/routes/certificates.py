"""ComplianceCertificate endpoints (nested under models)."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_enum, as_string, body, require
from routes.models import get_model
from services import cascade

bp = Blueprint("certificates", __name__)

CERT_TYPES = {"FLAMMABILITY_16CFR1633", "PROP65_CA", "TB117"}


def cert_view(c):
    return {
        "id": c["id"],
        "model_id": c["model_id"],
        "cert_type": c["cert_type"],
        "jurisdiction_state_code": c["jurisdiction_state_code"],
        "issued_on": c["issued_on"],
        "expires_on": c["expires_on"],
        "submitted_by_user_id": c["submitted_by_user_id"],
        "approved_by_user_id": c["approved_by_user_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def get_certificate(model, cert_id):
    cert = db.certificates.get(cert_id)
    if cert is None or cert["model_id"] != model["id"]:
        errors.raise_err(errors.ERR_CERTIFICATE_NOT_FOUND, "certificate not found within the model")
    return cert


@bp.route("/models/<mid>/certificates", methods=["POST"])
def create_certificate(mid):
    user_id, _ = middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    data = body()
    cert_type = as_enum(require(data, "cert_type"), "cert_type", CERT_TYPES)
    jurisdiction = as_string(require(data, "jurisdiction_state_code"), "jurisdiction_state_code")
    issued_raw = require(data, "issued_on")
    expires_raw = require(data, "expires_on")
    issued = clock.try_parse(issued_raw) if isinstance(issued_raw, str) else None
    expires = clock.try_parse(expires_raw) if isinstance(expires_raw, str) else None
    if issued is None or expires is None:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "issued_on and expires_on must be ISO8601 timestamps")
    if not expires > issued:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "expires_on must be strictly after issued_on")
    # tier 5: model must be CERT_REVIEW
    if model["status"] != "CERT_REVIEW":
        errors.raise_err(errors.ERR_MODEL_NOT_CERT_REVIEW, "model must be CERT_REVIEW")
    cert = {
        "id": db.new_id(),
        "model_id": model["id"],
        "cert_type": cert_type,
        "jurisdiction_state_code": jurisdiction,
        # input-supplied datetimes are echoed verbatim (comparisons parse them)
        "issued_on": issued_raw,
        "expires_on": expires_raw,
        "submitted_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "SUBMITTED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.certificates, cert)
    return response.success_object(cert_view(cert), 201)


@bp.route("/models/<mid>/certificates", methods=["GET"])
def list_certificates(mid):
    middleware.require_roles(middleware.ALL_ROLES)
    model = get_model(mid)
    cascade.touch_certificates()
    items = [c for c in db.certificates.values() if c["model_id"] == model["id"]]
    q = request.args.get("status")
    if q is not None:
        items = [c for c in items if c["status"] == q]
    items.sort(key=lambda c: c["_seq"])
    return response.success_list([cert_view(c) for c in items])


@bp.route("/models/<mid>/certificates/<certId>/approve", methods=["POST"])
def approve_certificate(mid, certId):
    user_id, _ = middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    cert = get_certificate(model, certId)
    cascade.touch_certificates()
    if cert["status"] != "SUBMITTED":
        errors.raise_err(errors.ERR_CERT_NOT_SUBMITTED, "certificate must be SUBMITTED")
    if user_id == cert["submitted_by_user_id"]:
        errors.raise_err(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "approver must differ from submitter",
        )
    cert["status"] = "APPROVED"
    cert["approved_by_user_id"] = user_id
    cascade.bump(cert)
    return response.success_object(cert_view(cert))


@bp.route("/models/<mid>/certificates/<certId>/revoke", methods=["POST"])
def revoke_certificate(mid, certId):
    user_id, _ = middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    cert = get_certificate(model, certId)
    cascade.touch_certificates()
    if cert["status"] != "APPROVED":
        errors.raise_err(errors.ERR_CERT_NOT_APPROVED, "certificate must be APPROVED")
    cert["status"] = "REVOKED"
    cascade.bump(cert)
    # cascade only when the revoked cert was the last APPROVED unexpired
    # FLAMMABILITY_16CFR1633 certificate for the model
    if cert["cert_type"] == "FLAMMABILITY_16CFR1633":
        if not cascade.approved_unexpired_flammability_certs(model["id"]):
            cascade.revoke_cascade(model)
    return response.success_object(cert_view(cert))
