"""Certification endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404, ref_or_404
from services import core

bp = Blueprint("certifications", __name__)


@bp.post("/efficiency/certifications")
def create_certification():
    require_roles({"ProgramManager"})
    body = get_body()
    contractor = ref_or_404(db.contractors, body.get("contractor_id"), "Contractor")
    cert = {
        "contractor_id": contractor["id"],
        "measure_type": body.get("measure_type"),
        "issued_on": body.get("issued_on"),
        "expires_on": body.get("expires_on"),
        "status": "ACTIVE",
    }
    db.stamp_new(cert)
    db.certifications[cert["id"]] = cert
    core.recompute_active_cert_count(contractor)
    db.touch(contractor)
    return success_object(cert, 201)


@bp.get("/efficiency/certifications")
def list_certifications():
    require_roles({"ProgramManager", "Contractor", "Inspector"})
    items = list(db.certifications.values())
    contractor_id = request.args.get("contractor_id")
    measure_type = request.args.get("measure_type")
    status = request.args.get("status")
    if contractor_id is not None:
        items = [c for c in items if c.get("contractor_id") == contractor_id]
    if measure_type is not None:
        items = [c for c in items if c.get("measure_type") == measure_type]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    return paginate(items)


@bp.get("/efficiency/certifications/<certification_id>")
def get_certification(certification_id):
    require_roles({"ProgramManager", "Contractor", "Inspector"})
    return success_object(fetch_or_404(db.certifications, certification_id, "Certification"))


@bp.post("/efficiency/certifications/<certification_id>/revoke")
def revoke_certification(certification_id):
    require_roles({"ProgramManager"})
    cert = fetch_or_404(db.certifications, certification_id, "Certification")
    if cert["status"] != "ACTIVE":
        raise errors.invalid_state(f"Certification in {cert['status']} cannot be revoked")
    cert["status"] = "REVOKED"
    db.touch(cert)
    contractor = db.contractors.get(cert["contractor_id"])
    if contractor is not None:
        core.recompute_active_cert_count(contractor)
        db.touch(contractor)
        if contractor.get("active_certification_count", 0) == 0 and contractor.get("status") == "APPROVED":
            core.suspend_contractor(contractor)
    return success_object(cert)
