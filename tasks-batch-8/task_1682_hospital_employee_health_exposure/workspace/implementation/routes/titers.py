"""Titer results: append-only immunity records."""
from flask import Blueprint

from db import base_fields, now, serialize, store
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.calculations import interpret_titer
from util import parse_dt

bp = Blueprint("titers", __name__)

DISEASES = {"HEP_B", "MEASLES", "MUMPS", "RUBELLA", "VARICELLA"}
ASSAY_TYPES = {"QUANTITATIVE", "QUALITATIVE"}
QUALITATIVE_RESULTS = {"REACTIVE", "NON_REACTIVE", "EQUIVOCAL"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.post("/employee-health/employees/<emp_id>/titer-results")
def create_titer(emp_id):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    emp = get_or_404(store.employees, emp_id)
    data = body()

    # Referential coherence: an optional screening link must belong to this employee.
    screening_id = data.get("screening_id")
    if screening_id is not None:
        screening = store.screenings.get(screening_id)
        if screening is None:
            raise ApiError("ERR_NOT_FOUND", "Resource not found: %s" % screening_id)
        if screening["employee_id"] != emp["id"]:
            raise ApiError(
                "ERR_SCREENING_EMPLOYEE_MISMATCH",
                "screening_id belongs to a different employee",
            )

    # Temporal: resulted_at must not be after the current logical clock time.
    resulted_at = parse_dt(data.get("resulted_at"))
    if resulted_at is not None and resulted_at > now():
        raise ApiError(
            "ERR_FUTURE_RESULT_DATE", "resulted_at must not be after the current time"
        )

    # Field shape.
    disease = check_enum(data.get("disease"), DISEASES, "disease")
    assay_type = check_enum(data.get("assay_type"), ASSAY_TYPES, "assay_type")
    if resulted_at is None:
        raise ApiError("ERR_INVALID_REQUEST", "resulted_at must be a valid ISO 8601 timestamp")
    numeric_value = data.get("numeric_value")
    qualitative_result = data.get("qualitative_result")
    if assay_type == "QUANTITATIVE":
        if not isinstance(numeric_value, (int, float)) or isinstance(numeric_value, bool):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "numeric_value is required for QUANTITATIVE assays",
            )
        qualitative_result = None  # ignored for QUANTITATIVE even when supplied
    else:
        check_enum(qualitative_result, QUALITATIVE_RESULTS, "qualitative_result")
        numeric_value = None  # ignored for QUALITATIVE even when supplied

    immunity_status = interpret_titer(disease, assay_type, numeric_value, qualitative_result)

    # TiterResult is append-only: id + created_at only, no updated_at/version.
    titer = base_fields(with_version=False)
    titer.update(
        {
            "employee_id": emp["id"],
            "screening_id": screening_id,
            "disease": disease,
            "assay_type": assay_type,
            "numeric_value": numeric_value,
            "qualitative_result": qualitative_result,
            "resulted_at": resulted_at,
            "immunity_status": immunity_status,
        }
    )
    store.titers[titer["id"]] = titer
    return success_object(serialize(titer), status=201)


@bp.get("/employee-health/titer-results")
def list_titers():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (lambda t: t["employee_id"] == user_id) if role == "StaffEmployee" else None
    items, meta = list_response(
        store.titers.values(),
        {
            "employee_id": lambda t: t["employee_id"],
            "screening_id": lambda t: t["screening_id"],
            "disease": lambda t: t["disease"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/titer-results/<rid>")
def get_titer(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    titer = get_or_404(store.titers, rid)
    staff_scope_check(role, user_id, titer["employee_id"])
    return success_object(serialize(titer))
