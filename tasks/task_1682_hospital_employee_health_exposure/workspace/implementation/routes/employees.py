"""Employee registration, listing, and reading."""
from flask import Blueprint

from db import base_fields, serialize, store
from errors import ApiError
from middleware import auth, body, check_bool, check_enum, check_str, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404
from util import parse_dt

bp = Blueprint("employees", __name__)

JOB_CATEGORIES = {"NURSE", "PHYSICIAN", "TECH", "HOUSEKEEPING", "OTHER"}


@bp.post("/employee-health/employees")
def create_employee():
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    data = body()

    # Uniqueness/overlap family (priority 10) precedes field shape (priority 11).
    ref = data.get("employee_ref")
    if isinstance(ref, str) and ref:
        if any(e["employee_ref"] == ref for e in store.employees.values()):
            raise ApiError("ERR_DUPLICATE_EMPLOYEE_REF", "employee_ref already registered")

    # Field shape: required fields present, enum members valid.
    check_str(data.get("employee_ref"), "employee_ref")
    check_str(data.get("full_name"), "full_name")
    check_enum(data.get("job_category"), JOB_CATEGORIES, "job_category")
    check_str(data.get("department"), "department")
    hire_date = parse_dt(data.get("hire_date"))
    if hire_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "hire_date must be a valid ISO 8601 timestamp")
    requires_respirator = check_bool(data.get("requires_respirator"), "requires_respirator")

    emp = base_fields()
    emp.update(
        {
            "employee_ref": data["employee_ref"],
            "full_name": data["full_name"],
            "job_category": data["job_category"],
            "department": data["department"],
            "hire_date": hire_date,
            "requires_respirator": requires_respirator,
            "status": "PREPLACEMENT",
            "compliance_posture": "CLEAR",
            "active_hold_count": 0,
            "open_restriction_count": 0,
        }
    )
    store.employees[emp["id"]] = emp
    return success_object(serialize(emp), status=201)


@bp.get("/employee-health/employees")
def list_employees():
    user_id, role = auth()
    require_role(role, {
        "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
        "SafetyOfficer", "StaffEmployee",
    })
    scope = None
    if role == "StaffEmployee":
        scope = lambda e: e["id"] == user_id  # noqa: E731
    items, meta = list_response(
        store.employees.values(),
        {
            "status": lambda e: e["status"],
            "compliance_posture": lambda e: e["compliance_posture"],
            "department": lambda e: e["department"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/employees/<rid>")
def get_employee(rid):
    user_id, role = auth()
    require_role(role, {
        "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
        "SafetyOfficer", "StaffEmployee",
    })
    # Self-scope (priority 3) is evaluated before existence (priority 4): the
    # employee id in the path is directly comparable to X-User-ID.
    if role == "StaffEmployee" and user_id != rid:
        raise ApiError("ERR_OWNERSHIP_REQUIRED", "StaffEmployee may read only their own record")
    emp = get_or_404(store.employees, rid)
    return success_object(serialize(emp))
