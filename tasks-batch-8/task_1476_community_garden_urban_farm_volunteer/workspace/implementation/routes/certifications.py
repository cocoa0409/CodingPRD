"""Training certifications (PRD section 3.2)."""
from flask import Blueprint, request

import clock
import db
import services
from app_util import body
from errors import err, err_invalid_request, err_not_found, err_sod, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import opt_str, pagination_args, parse_dt, req_enum, require_field

bp = Blueprint("certifications", __name__)

CERT_TYPES = {"PRODUCE_SAFETY", "SUPERVISION", "TOOL_SAFETY"}
ISSUERS = ["GardenAdmin", "FoodSafetyOfficer"]


@bp.post("/api/certifications")
def issue_certification():
    ctx = require_auth()
    require_role(ctx, ISSUERS)
    data = body()
    # existence (tier 3): subject volunteer
    volunteer_id = require_field(data, "volunteer_id")
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise err_not_found("volunteer")
    # segregation of duties (tier 4): issuer != subject.
    # GardenAdmin identity is opaque and never equals a Volunteer id, so it always passes.
    if ctx.role != "GardenAdmin" and ctx.user_id == volunteer_id:
        raise err_sod()
    # shape (tier 5)
    cert_type = req_enum(data, "cert_type", CERT_TYPES)
    expires_raw = require_field(data, "expires_at")
    expires_at = parse_dt(expires_raw, "expires_at")
    if expires_at <= clock.now():
        raise err_invalid_request("expires_at must be strictly after the issuance clock time")
    # uniqueness (tier 11): at most one ACTIVE cert per (volunteer, cert_type)
    if services.has_active_cert(volunteer_id, cert_type):
        raise err("ERR_DUPLICATE_ACTIVE_CERT", "volunteer already holds an ACTIVE cert of this type")
    rec = services.create_record({
        "volunteer_id": volunteer_id,
        "cert_type": cert_type,
        "issued_at": clock.now(),
        "expires_at": expires_at,
        "status": "ACTIVE",
        "revoked_reason": None,
    })
    db.certifications[rec["id"]] = rec
    return ok(services.certification_view(rec), status=201)


@bp.get("/api/certifications")
def list_certifications():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.certifications.values(),
        {"volunteer_id": "volunteer_id", "cert_type": "cert_type", "status": "status"},
        request.args, services.certification_view,
    )
    total = len(items)
    page = items[offset:offset + limit]
    return ok([services.certification_view(c) for c in page], pagination=(limit, offset, total))


def _get_cert(certificationId):
    cert = db.certifications.get(certificationId)
    if cert is None:
        raise err_not_found("certification")
    return cert


@bp.get("/api/certifications/<certificationId>")
def get_certification(certificationId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.certification_view(_get_cert(certificationId)))


@bp.post("/api/certifications/<certificationId>/revoke")
def revoke_certification(certificationId):
    ctx = require_auth()
    require_role(ctx, ISSUERS)
    cert = _get_cert(certificationId)
    data = body()
    # shape (tier 5) precedes from-state (tier 6)
    reason = require_field(data, "revoked_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise err_invalid_request("revoked_reason must be non-empty")
    if cert["status"] != "ACTIVE":
        raise err_state("CERTIFICATION")
    cert["status"] = "REVOKED"
    cert["revoked_reason"] = reason
    services.bump(cert)
    # cascade: PRODUCE_SAFETY revocation forces the subject's SUBMITTED logs back to DRAFT
    if cert["cert_type"] == "PRODUCE_SAFETY":
        for log in db.harvests.values():
            if log["logged_by_volunteer_id"] == cert["volunteer_id"] and log["status"] == "SUBMITTED":
                log["status"] = "DRAFT"
                services.bump(log)
    return ok(services.certification_view(cert))
