"""Complaint endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404, ref_or_404
from services import core

bp = Blueprint("complaints", __name__)


@bp.post("/efficiency/complaints")
def create_complaint():
    role, user_id = require_roles({"Customer", "ProgramManager"})
    body = get_body()
    customer = ref_or_404(db.customers, body.get("customer_id"), "Customer")
    contractor = ref_or_404(db.contractors, body.get("contractor_id"), "Contractor")
    project_id = body.get("project_id")
    if project_id is not None:
        ref_or_404(db.projects, project_id, "Project")
    # Customer role must be acting as the named customer
    if role == "Customer" and customer["id"] != user_id:
        raise errors.not_resource_owner()
    complaint = {
        "customer_id": customer["id"],
        "contractor_id": contractor["id"],
        "project_id": project_id,
        "category": body.get("category"),
        "severity": body.get("severity"),
        "description": body.get("description"),
        "status": "OPEN",
    }
    db.stamp_new(complaint)
    db.complaints[complaint["id"]] = complaint
    core.recompute_complaint_count(contractor)
    return success_object(complaint, 201)


@bp.get("/efficiency/complaints")
def list_complaints():
    require_roles({"ProgramManager", "Contractor", "Customer"})
    items = list(db.complaints.values())
    customer_id = request.args.get("customer_id")
    contractor_id = request.args.get("contractor_id")
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    if customer_id is not None:
        items = [c for c in items if c.get("customer_id") == customer_id]
    if contractor_id is not None:
        items = [c for c in items if c.get("contractor_id") == contractor_id]
    if project_id is not None:
        items = [c for c in items if c.get("project_id") == project_id]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    if severity is not None:
        items = [c for c in items if c.get("severity") == severity]
    return paginate(items)


@bp.get("/efficiency/complaints/<complaint_id>")
def get_complaint(complaint_id):
    require_roles({"ProgramManager", "Contractor", "Customer"})
    return success_object(fetch_or_404(db.complaints, complaint_id, "Complaint"))


@bp.post("/efficiency/complaints/<complaint_id>/start_review")
def start_review(complaint_id):
    require_roles({"ProgramManager"})
    complaint = fetch_or_404(db.complaints, complaint_id, "Complaint")
    if complaint["status"] != "OPEN":
        raise errors.invalid_state(f"Complaint in {complaint['status']} cannot move to IN_REVIEW")
    complaint["status"] = "IN_REVIEW"
    db.touch(complaint)
    return success_object(complaint)


@bp.post("/efficiency/complaints/<complaint_id>/resolve")
def resolve_complaint(complaint_id):
    require_roles({"ProgramManager"})
    complaint = fetch_or_404(db.complaints, complaint_id, "Complaint")
    if complaint["status"] not in ("IN_REVIEW", "ESCALATED"):
        raise errors.invalid_state(f"Complaint in {complaint['status']} cannot be resolved")
    complaint["status"] = "RESOLVED"
    db.touch(complaint)
    contractor = db.contractors.get(complaint["contractor_id"])
    if contractor is not None:
        core.recompute_complaint_count(contractor)
    return success_object(complaint)


@bp.post("/efficiency/complaints/<complaint_id>/escalate")
def escalate_complaint(complaint_id):
    require_roles({"ProgramManager"})
    complaint = fetch_or_404(db.complaints, complaint_id, "Complaint")
    if complaint["status"] not in ("OPEN", "IN_REVIEW"):
        raise errors.invalid_state(f"Complaint in {complaint['status']} cannot be escalated")
    if complaint.get("severity") not in ("HIGH", "CRITICAL"):
        raise errors.severity_too_low()
    complaint["status"] = "ESCALATED"
    db.touch(complaint)
    contractor = db.contractors.get(complaint["contractor_id"])
    if contractor is not None:
        core.recompute_complaint_count(contractor)
        if core.count_escalated_complaints(contractor["id"]) >= 3:
            core.suspend_contractor(contractor)
    return success_object(complaint)
