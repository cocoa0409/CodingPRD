"""ExemptionCertificate endpoints (§3.7)."""
from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_INTERVAL, ERR_CERTIFICATE_OVERLAP,
    ERR_INVALID_STATE, ERR_VALIDATION_FAILED,
)
from middleware import require
from response import object_response, array_response
from services import common, serializers

bp = Blueprint("certificates", __name__)

READ_ROLES = ["Seller", "PlatformAdmin", "TaxPreparer", "TaxApprover", "Auditor"]


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open interval intersection; adjacency (a_to == b_from) allowed."""
    return a_from < b_to and b_from < a_to


@bp.post("/exemption-certificates")
@require("Seller")
def create_certificate():
    body = common.get_body()
    seller_id = common.require_str(body, "seller_id")
    jurisdiction_id = common.require_str(body, "jurisdiction_id")
    customer_ref = common.require_str(body, "customer_ref")
    exempt_category_code = common.require_str(body, "exempt_category_code")

    common.resolve_fk(db.sellers, seller_id, "seller_id")
    common.resolve_fk(db.tax_jurisdictions, jurisdiction_id, "jurisdiction_id")

    valid_from = common.parse_dt(body, "valid_from")
    valid_to = common.parse_dt(body, "valid_to")

    # Interval well-formedness (priority 7).
    if not (valid_to > valid_from):
        raise APIError(ERR_INVALID_INTERVAL, "valid_to must be strictly after valid_from")

    # Overlap against existing ACTIVE certs for the same key (priority 8).
    for cert in db.exemption_certificates.values():
        if cert["status"] != "ACTIVE":
            continue
        if (cert["seller_id"] == seller_id
                and cert["jurisdiction_id"] == jurisdiction_id
                and cert["customer_ref"] == customer_ref
                and cert["exempt_category_code"] == exempt_category_code):
            if _overlaps(valid_from, valid_to, cert["valid_from"], cert["valid_to"]):
                raise APIError(ERR_CERTIFICATE_OVERLAP, "overlapping active exemption certificate")

    rec = {
        "seller_id": seller_id,
        "jurisdiction_id": jurisdiction_id,
        "customer_ref": customer_ref,
        "exempt_category_code": exempt_category_code,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "ACTIVE",
    }
    common.stamp_create(rec)
    db.exemption_certificates[rec["id"]] = rec
    return object_response(serializers.exemption_certificate(rec), 201)


@bp.get("/exemption-certificates/<rec_id>")
@require(*READ_ROLES)
def get_certificate(rec_id):
    rec = common.get_or_404(db.exemption_certificates, rec_id, "exemption certificate")
    return object_response(serializers.exemption_certificate(rec))


@bp.get("/exemption-certificates")
@require(*READ_ROLES)
def list_certificates():
    records = list(db.exemption_certificates.values())
    sid = request.args.get("seller_id")
    jid = request.args.get("jurisdiction_id")
    cref = request.args.get("customer_ref")
    if sid is not None:
        records = [r for r in records if r["seller_id"] == sid]
    if jid is not None:
        records = [r for r in records if r["jurisdiction_id"] == jid]
    if cref is not None:
        records = [r for r in records if r["customer_ref"] == cref]
    items, limit, offset, total = common.paginate(records, serializers.exemption_certificate)
    return array_response(items, limit, offset, total)


@bp.post("/exemption-certificates/<rec_id>/revoke")
@require("Seller")
def revoke_certificate(rec_id):
    rec = common.get_or_404(db.exemption_certificates, rec_id, "exemption certificate")
    if rec["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "certificate must be ACTIVE to revoke")
    rec["status"] = "REVOKED"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "ExemptionCertificate", rec["id"], "REVOKE_CERTIFICATE")
    return object_response(serializers.exemption_certificate(rec))


@bp.post("/exemption-certificates/<rec_id>/reinstate")
@require("Seller")
def reinstate_certificate(rec_id):
    rec = common.get_or_404(db.exemption_certificates, rec_id, "exemption certificate")
    if rec["status"] != "REVOKED":
        raise APIError(ERR_INVALID_STATE, "certificate must be REVOKED to reinstate")
    # Window must still be open: clock strictly before valid_to.
    if not (db.now() < rec["valid_to"]):
        raise APIError(ERR_VALIDATION_FAILED, "certificate window has ended; cannot reinstate")
    rec["status"] = "ACTIVE"
    common.touch(rec)
    common.append_audit(rec["seller_id"], "ExemptionCertificate", rec["id"], "REINSTATE_CERTIFICATE")
    return object_response(serializers.exemption_certificate(rec))
