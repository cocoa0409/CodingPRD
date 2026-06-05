"""Dependent registration + verification loop endpoints (PRD §3.3, §2.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize, current_user_id,
    BENEFITS_ADMIN, DEPENDENT_VERIFIER, COMPLIANCE_OFFICER, PAYROLL_OFFICER,
)
import response
from services import common as C
from routes._helpers import get_or_404

bp = Blueprint("dependents", __name__)

ALL_ROLES = {BENEFITS_ADMIN, DEPENDENT_VERIFIER, COMPLIANCE_OFFICER, PAYROLL_OFFICER}
RELATIONSHIPS = {"SPOUSE", "CHILD"}


@bp.route("/employees/<emp_id>/dependents", methods=["POST"])
def create_dependent(emp_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    emp = get_or_404(db.employees, emp_id, "Employee")
    body = C.get_body()
    C.require_fields(body, ["relationship", "full_name", "date_of_birth"])
    relationship = C.require_enum(body, "relationship", RELATIONSHIPS)
    full_name = C.require_str(body, "full_name")
    dob = body["date_of_birth"]
    C.parse_iso(dob)  # validate ISO 8601

    dep = C.new_common_fields()
    dep.update({
        "employee_id": emp_id,
        "relationship": relationship,
        "full_name": full_name,
        "date_of_birth": dob,
        "verification_status": "PENDING",
        "verified_by_user_id": None,
    })
    db.dependents[dep["id"]] = dep
    return response.ok_object(C.serialize(dep), 201)


@bp.route("/dependents/<dep_id>", methods=["GET"])
def get_dependent(dep_id):
    role = authenticate()
    authorize(role, ALL_ROLES)
    dep = get_or_404(db.dependents, dep_id, "Dependent")
    return response.ok_object(C.serialize(dep), 200)


@bp.route("/dependents", methods=["GET"])
def list_dependents():
    role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = C.parse_pagination()
    employee_id = request.args.get("employee_id")
    verification_status = request.args.get("verification_status")
    items = list(db.dependents.values())
    if employee_id is not None:
        items = [d for d in items if d["employee_id"] == employee_id]
    if verification_status is not None:
        items = [d for d in items if d["verification_status"] == verification_status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/dependents/<dep_id>/request-info", methods=["POST"])
def request_info(dep_id):
    role = authenticate()
    authorize(role, {DEPENDENT_VERIFIER})
    dep = get_or_404(db.dependents, dep_id, "Dependent")
    if dep["verification_status"] != "PENDING":
        raise E.invalid_state("Dependent must be PENDING to request info")
    dep["verification_status"] = "INFO_REQUESTED"
    C.touch(dep)
    return response.ok_object(C.serialize(dep), 200)


@bp.route("/dependents/<dep_id>/resubmit", methods=["POST"])
def resubmit(dep_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    dep = get_or_404(db.dependents, dep_id, "Dependent")
    if dep["verification_status"] != "INFO_REQUESTED":
        raise E.invalid_state("Dependent must be INFO_REQUESTED to resubmit")
    dep["verification_status"] = "PENDING"
    C.touch(dep)
    return response.ok_object(C.serialize(dep), 200)


@bp.route("/dependents/<dep_id>/verify", methods=["POST"])
def verify(dep_id):
    role = authenticate()
    authorize(role, {DEPENDENT_VERIFIER})
    dep = get_or_404(db.dependents, dep_id, "Dependent")
    # State precondition (priority 5) before business safety (priority 6).
    if dep["verification_status"] != "PENDING":
        raise E.invalid_state("Dependent must be PENDING to verify")
    # Segregation (priority 6): verifier X-User-ID must differ from the owning
    # employee's id (an employee cannot verify their own dependent).
    if current_user_id() == dep["employee_id"]:
        raise E.segregation("Verifier may not verify their own dependent")
    dep["verification_status"] = "VERIFIED"
    dep["verified_by_user_id"] = current_user_id()
    C.touch(dep)
    return response.ok_object(C.serialize(dep), 200)


@bp.route("/dependents/<dep_id>/reject", methods=["POST"])
def reject(dep_id):
    role = authenticate()
    authorize(role, {DEPENDENT_VERIFIER})
    dep = get_or_404(db.dependents, dep_id, "Dependent")
    if dep["verification_status"] != "PENDING":
        raise E.invalid_state("Dependent must be PENDING to reject")
    dep["verification_status"] = "REJECTED"
    C.touch(dep)
    return response.ok_object(C.serialize(dep), 200)
