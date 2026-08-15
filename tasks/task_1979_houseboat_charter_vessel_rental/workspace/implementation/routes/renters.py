"""Renter registration, safety certificates, certificate decisions (PRD §3.3)."""

from flask import Blueprint

import common
import db
import errors
import response
from middleware import check_renter_owner, require_roles
from services import risk

bp = Blueprint("renters", __name__)

ISSUING_AUTHORITIES = ("NASBLA", "USCG", "STATE")
CERT_DECISIONS = ("VERIFY", "REJECT", "REVOKE")


@bp.post("/renters")
@require_roles("Renter")
def create_renter(user_id, role):
    body = common.json_body()
    full_name = common.as_str(common.req_field(body, "full_name"), "full_name")
    email = common.as_str(common.req_field(body, "email"), "email")
    dob = common.parse_date(common.req_field(body, "date_of_birth"), "date_of_birth")

    rec = db.base_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "date_of_birth": dob,
        "qualification_status": "UNVERIFIED",
        "risk_score_lifetime": 0,
        "risk_score_rolling_24m": 0,
        "deposit_multiplier": 1.0,
    })
    db.insert("renters", rec)
    return response.ok(common.renter_out(rec), status=201)


@bp.get("/renters/<rid>")
@require_roles("Renter", "DockStaff", "FleetManager", "Mechanic")
def get_renter(rid, user_id, role):
    check_renter_owner(rid, user_id, role)
    renter = db.get("renters", rid)
    if renter is None:
        errors.err(errors.ERR_NOT_FOUND, f"Renter {rid} does not exist")
    return response.ok(common.renter_out(renter))


@bp.post("/renters/<rid>/certificates")
@require_roles("Renter")
def submit_certificate(rid, user_id, role):
    check_renter_owner(rid, user_id, role)
    renter = db.get("renters", rid)
    if renter is None:
        errors.err(errors.ERR_NOT_FOUND, f"Renter {rid} does not exist")
    body = common.json_body()
    cert_number = common.as_str(common.req_field(body, "cert_number"), "cert_number")
    authority = common.as_enum(
        common.req_field(body, "issuing_authority"), "issuing_authority", ISSUING_AUTHORITIES
    )
    issued_on = common.parse_date(common.req_field(body, "issued_on"), "issued_on")
    expires_on = common.parse_date(common.req_field(body, "expires_on"), "expires_on")

    rec = db.base_record()
    rec.update({
        "renter_id": rid,
        "cert_number": cert_number,
        "issuing_authority": authority,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "SUBMITTED",
    })
    db.insert("certificates", rec)
    return response.ok(common.certificate_out(rec), status=201)


@bp.get("/renters/<rid>/certificates")
@require_roles("Renter", "DockStaff", "FleetManager")
def list_certificates(rid, user_id, role):
    check_renter_owner(rid, user_id, role)
    renter = db.get("renters", rid)
    if renter is None:
        errors.err(errors.ERR_NOT_FOUND, f"Renter {rid} does not exist")
    certs = [c for c in db.all_of("certificates") if c["renter_id"] == rid]
    page, total, limit, offset = common.paginate(certs)
    return response.list_ok(
        [common.certificate_out(c) for c in page], total, limit, offset
    )


@bp.post("/certificates/<cid>/decision")
@require_roles("DockStaff", "FleetManager")
def certificate_decision(cid, user_id, role):
    cert = db.get("certificates", cid)
    if cert is None:
        errors.err(errors.ERR_NOT_FOUND, f"SafetyCertificate {cid} does not exist")
    body = common.json_body()
    decision = common.as_enum(
        common.req_field(body, "decision"), "decision", CERT_DECISIONS
    )
    # REVOKE is the FleetManager's prerogative (PRD §3.3).
    if decision == "REVOKE" and role != "FleetManager":
        errors.err(errors.ERR_FORBIDDEN, "REVOKE requires the FleetManager role")

    if decision in ("VERIFY", "REJECT"):
        if cert["status"] != "SUBMITTED":
            errors.err(
                errors.ERR_INVALID_STATE,
                f"Certificate in state {cert['status']} cannot be decided",
            )
        cert["status"] = "VERIFIED" if decision == "VERIFY" else "REJECTED"
    else:  # REVOKE
        if cert["status"] != "VERIFIED":
            errors.err(
                errors.ERR_INVALID_STATE,
                f"Certificate in state {cert['status']} cannot be revoked",
            )
        cert["status"] = "REVOKED"
    db.touch(cert)

    renter = db.get("renters", cert["renter_id"])
    if renter is not None:
        risk.recompute_qualification(renter)
    return response.ok(common.certificate_out(cert))
