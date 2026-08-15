"""Work restrictions (physician-imposed) and return-to-work clearance requests."""
from datetime import datetime, timezone

from flask import Blueprint

from db import base_fields, serialize, store
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.core import create_restriction
from util import parse_dt

bp = Blueprint("restrictions", __name__)

RESTRICTION_TYPES = {"NO_PATIENT_CONTACT", "NO_PROCEDURES", "MODIFIED_DUTY", "FULL_EXCLUSION"}
MAX_DT = datetime.max.replace(tzinfo=timezone.utc)

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


def _half_open_intersect(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection; null end = +infinity; adjacency allowed."""
    a_end = a_end if a_end is not None else MAX_DT
    b_end = b_end if b_end is not None else MAX_DT
    return a_start < b_end and b_start < a_end


@bp.post("/employee-health/employees/<emp_id>/work-restrictions")
def create_restriction_endpoint(emp_id):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthPhysician"})
    emp = get_or_404(store.employees, emp_id)
    data = body()

    # Referential coherence: optional exposure linkage must belong to this employee.
    case_id = data.get("exposure_case_id")
    if case_id is not None:
        case = store.cases.get(case_id)
        if case is None:
            raise ApiError("ERR_NOT_FOUND", "Resource not found: %s" % case_id)
        if case["employee_id"] != emp["id"]:
            raise ApiError(
                "ERR_CASE_EMPLOYEE_MISMATCH",
                "exposure_case_id belongs to a different employee",
            )

    start_date = parse_dt(data.get("start_date"))
    end_date = parse_dt(data.get("end_date")) if data.get("end_date") is not None else None

    # Uniqueness/overlap (priority 10): half-open overlap with another ACTIVE
    # restriction of the same employee is rejected; adjacency is permitted.
    if start_date is not None and (data.get("end_date") is None or end_date is not None):
        for other in store.restrictions.values():
            if other["employee_id"] != emp["id"] or other["status"] != "ACTIVE":
                continue
            if _half_open_intersect(start_date, end_date, other["start_date"], other["end_date"]):
                raise ApiError(
                    "ERR_WORK_RESTRICTION_OVERLAP",
                    "The restriction interval intersects another ACTIVE restriction",
                )

    # Field shape.
    restriction_type = check_enum(
        data.get("restriction_type"), RESTRICTION_TYPES, "restriction_type"
    )
    if start_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "start_date must be a valid ISO 8601 timestamp")
    if data.get("end_date") is not None and end_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "end_date must be a valid ISO 8601 timestamp")
    if end_date is not None and end_date < start_date:
        raise ApiError("ERR_INVALID_REQUEST", "end_date must not be earlier than start_date")

    r = create_restriction(emp["id"], restriction_type, start_date, end_date, "MANUAL",
                           exposure_case_id=case_id)
    return success_object(serialize(r), status=201)


@bp.get("/employee-health/work-restrictions")
def list_restrictions():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (lambda r: r["employee_id"] == user_id) if role == "StaffEmployee" else None
    items, meta = list_response(
        store.restrictions.values(),
        {
            "employee_id": lambda r: r["employee_id"],
            "exposure_case_id": lambda r: r["exposure_case_id"],
            "status": lambda r: r["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/work-restrictions/<rid>")
def get_restriction(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    r = get_or_404(store.restrictions, rid)
    staff_scope_check(role, user_id, r["employee_id"])
    return success_object(serialize(r))


@bp.post("/employee-health/work-restrictions/<rid>/clearances")
def request_clearance(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    restriction = get_or_404(store.restrictions, rid)
    if restriction["status"] != "ACTIVE":
        raise ApiError("ERR_RESTRICTION_NOT_ACTIVE", "Restriction is not ACTIVE")
    clearance = base_fields()
    clearance.update(
        {
            "restriction_id": restriction["id"],
            "status": "PENDING",
            "requested_by_user_id": user_id,
            "decided_by_user_id": None,
            "decided_at": None,
            "decision_note": None,
        }
    )
    store.clearances[clearance["id"]] = clearance
    return success_object(serialize(clearance), status=201)
