"""Contractor endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404
from services import core

bp = Blueprint("contractors", __name__)


@bp.post("/efficiency/contractors")
def create_contractor():
    require_roles({"ProgramManager"})
    body = get_body()
    contractor = {
        "legal_name": body.get("legal_name"),
        "license_number": body.get("license_number"),
        "sector": body.get("sector"),
        "service_zip_codes": list(body.get("service_zip_codes") or []),
        "qa_score_bps": 10000,
        "qa_window_size": 10,
        "active_certification_count": 0,
        "on_time_installs": 0,
        "late_installs": 0,
        "complaint_count_90d": 0,
        "status": "APPLIED",
    }
    db.stamp_new(contractor)
    db.contractors[contractor["id"]] = contractor
    return success_object(contractor, 201)


@bp.get("/efficiency/contractors")
def list_contractors():
    require_roles({"ProgramManager", "Inspector"})
    items = list(db.contractors.values())
    status = request.args.get("status")
    sector = request.args.get("sector")
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    if sector is not None:
        items = [c for c in items if c.get("sector") == sector]
    return paginate(items)


@bp.get("/efficiency/contractors/<contractor_id>")
def get_contractor(contractor_id):
    require_roles({"ProgramManager", "Contractor", "Inspector"})
    contractor = fetch_or_404(db.contractors, contractor_id, "Contractor")
    core.recompute_complaint_count(contractor)
    return success_object(contractor)


@bp.post("/efficiency/contractors/<contractor_id>/approve")
def approve_contractor(contractor_id):
    require_roles({"ProgramManager"})
    contractor = fetch_or_404(db.contractors, contractor_id, "Contractor")
    if contractor["status"] != "APPLIED":
        raise errors.invalid_state(f"Contractor in {contractor['status']} cannot be approved")
    core.recompute_active_cert_count(contractor)
    if contractor.get("active_certification_count", 0) < 1:
        raise errors.certification_missing()
    db.touch(contractor)
    contractor["status"] = "APPROVED"
    db.touch(contractor)
    return success_object(contractor)


@bp.post("/efficiency/contractors/<contractor_id>/suspend")
def suspend_contractor(contractor_id):
    require_roles({"ProgramManager"})
    contractor = fetch_or_404(db.contractors, contractor_id, "Contractor")
    if contractor["status"] != "APPROVED":
        raise errors.invalid_state(f"Contractor in {contractor['status']} cannot be suspended")
    core.suspend_contractor(contractor)
    return success_object(contractor)


@bp.post("/efficiency/contractors/<contractor_id>/reinstate")
def reinstate_contractor(contractor_id):
    require_roles({"ProgramManager"})
    contractor = fetch_or_404(db.contractors, contractor_id, "Contractor")
    if contractor["status"] != "SUSPENDED":
        raise errors.invalid_state(f"Contractor in {contractor['status']} cannot be reinstated")
    core.recompute_active_cert_count(contractor)
    if contractor.get("active_certification_count", 0) < 1:
        raise errors.certification_missing()
    contractor["status"] = "APPROVED"
    db.touch(contractor)
    return success_object(contractor)


@bp.post("/efficiency/contractors/<contractor_id>/terminate")
def terminate_contractor(contractor_id):
    require_roles({"ProgramManager"})
    contractor = fetch_or_404(db.contractors, contractor_id, "Contractor")
    if contractor["status"] not in ("APPROVED", "SUSPENDED"):
        raise errors.invalid_state(f"Contractor in {contractor['status']} cannot be terminated")
    for wo in db.work_orders.values():
        if wo.get("contractor_id") == contractor_id and wo.get("status") in ("SCHEDULED", "IN_PROGRESS"):
            raise errors.contractor_busy()
    contractor["status"] = "TERMINATED"
    db.touch(contractor)
    core.withdraw_open_leads(contractor_id)
    return success_object(contractor)
