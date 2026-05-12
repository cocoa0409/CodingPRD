"""Certificate routes (reissue, revoke, public verify)."""

from flask import Blueprint, request

from middleware import require_role
from response import success
from services import certificate
from services.serializers import serialize_certificate

bp = Blueprint("certificates", __name__)


@bp.post("/certificates/<cert_id>/reissue")
def reissue(cert_id):
    require_role("CertificateOfficer")
    new_cert = certificate.reissue_certificate(cert_id, request.get_json(silent=True) or {})
    return success(serialize_certificate(new_cert), 201)


@bp.post("/certificates/<cert_id>/revoke")
def revoke(cert_id):
    require_role("PlatformAdmin")
    cert = certificate.revoke_certificate(cert_id, request.get_json(silent=True) or {})
    return success(serialize_certificate(cert), 200)


@bp.get("/certificates/verify/<verification_code>")
def verify(verification_code):
    require_role("Applicant", "PlatformAdmin", "CertificateOfficer",
                 "Reviewer", "LeadReviewer", "CatalogManager")
    payload = certificate.verify_certificate(verification_code)
    return success(payload, 200)
