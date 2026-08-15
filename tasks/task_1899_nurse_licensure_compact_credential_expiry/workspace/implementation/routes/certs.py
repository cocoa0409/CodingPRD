from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_CERTIFICATION_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from services.derived import invalidate_items_for, recompute_posture

bp = Blueprint("certs", __name__)

CERT_TYPES = ["BLS", "ACLS", "PALS", "CCRN", "CNOR", "OCN"]

CREATE_SCHEMA = {
    "nurse_id": ("string", True, None),
    "cert_type": ("string", True, CERT_TYPES),
    "issuing_body": ("string", True, None),
    "obtained_on": ("date", True, None),
    "expires_on": ("date", True, None),
}

RENEW_SCHEMA = {
    "new_expires_on": ("date", True, None),
}


@bp.route("/credentialing/certifications", methods=["POST"])
def create_certification():
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    body = validate_body(get_body(), CREATE_SCHEMA)
    nurse = get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    cert = create_entity("certifications", {
        "nurse_id": nurse["id"],
        "cert_type": body["cert_type"],
        "issuing_body": body["issuing_body"],
        "obtained_on": body["obtained_on"].isoformat(),
        "expires_on": body["expires_on"].isoformat(),
        "status": "ACTIVE",
    })
    recompute_posture(nurse)
    return success_object(serialize("certifications", cert), 201)


@bp.route("/credentialing/certifications", methods=["GET"])
def list_certifications():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("certifications")
    for param in ("nurse_id", "cert_type", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [c for c in rows if c[param] == value]
    total = len(rows)
    return success_list([serialize("certifications", c) for c in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/certifications/<certId>", methods=["GET"])
def get_certification(certId):
    auth_context()
    cert = get_or_404("certifications", certId, ERR_NOT_FOUND, "Certification not found")
    return success_object(serialize("certifications", cert))


@bp.route("/credentialing/certifications/<certId>/renew", methods=["POST"])
def renew_certification(certId):
    user_id, role = auth_context()
    require_role(role, {"CredentialingSpecialist"})
    cert = get_or_404("certifications", certId, ERR_NOT_FOUND, "Certification not found")
    body = validate_body(get_body(allow_empty=False), RENEW_SCHEMA)
    if cert["status"] != "EXPIRED":
        raise ApiError(ERR_INVALID_CERTIFICATION_STATE, "Only an EXPIRED certification can be renewed", 409)
    new_expires_on = body["new_expires_on"]
    if new_expires_on <= db.current_date():
        raise ApiError(ERR_INVALID_DATE_RANGE, "new_expires_on must be strictly after the current date", 422)
    cert["expires_on"] = new_expires_on.isoformat()
    cert["status"] = "ACTIVE"
    touch(cert)
    nurse = db.STORES["nurses"].get(cert["nurse_id"])
    if nurse:
        recompute_posture(nurse)
    return success_object(serialize("certifications", cert))


@bp.route("/credentialing/certifications/<certId>/revoke", methods=["POST"])
def revoke_certification(certId):
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    cert = get_or_404("certifications", certId, ERR_NOT_FOUND, "Certification not found")
    if cert["status"] not in ("ACTIVE", "EXPIRED"):
        raise ApiError(ERR_INVALID_CERTIFICATION_STATE, "Only ACTIVE or EXPIRED certifications can be revoked", 409)
    was_active = cert["status"] == "ACTIVE"
    cert["status"] = "REVOKED"
    touch(cert)
    if was_active:
        # Same item-invalidation cascade as expiry.
        invalidate_items_for(cert["id"])
    nurse = db.STORES["nurses"].get(cert["nurse_id"])
    if nurse:
        recompute_posture(nurse)
    return success_object(serialize("certifications", cert))
