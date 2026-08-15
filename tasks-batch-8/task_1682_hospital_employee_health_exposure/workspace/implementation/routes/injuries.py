"""Injury reports and the workers' compensation lifecycle."""
from flask import Blueprint

from db import base_fields, now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.calculations import osha_recordable
from util import parse_dt

bp = Blueprint("injuries", __name__)

INJURY_TYPES = {"NEEDLESTICK", "SPLASH", "FALL", "LIFT", "OTHER"}
WC_TARGETS = {"WC_SUBMITTED", "WC_ACCEPTED", "WC_DENIED", "APPEALED"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.post("/employee-health/employees/<emp_id>/injury-reports")
def create_injury(emp_id):
    user_id, role = auth()
    require_role(role, {"SafetyOfficer"})
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

    # Temporal: injury_datetime must not be after the current logical time.
    injury_dt = parse_dt(data.get("injury_datetime"))
    if injury_dt is not None and injury_dt > now():
        raise ApiError(
            "ERR_COMPLETION_OUT_OF_RANGE",
            "injury_datetime must not be after the current time",
        )

    # Field shape.
    injury_type = check_enum(data.get("injury_type"), INJURY_TYPES, "injury_type")
    if injury_dt is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "injury_datetime must be a valid ISO 8601 timestamp"
        )

    injury = base_fields()
    injury.update(
        {
            "employee_id": emp["id"],
            "exposure_case_id": case_id,
            "injury_type": injury_type,
            "injury_datetime": injury_dt,
            "origin": "MANUAL",
            "osha_recordable": False,
            "wc_claim_number": None,
            "status": "FILED",
        }
    )
    injury["osha_recordable"] = osha_recordable(injury)
    store.injuries[injury["id"]] = injury
    return success_object(serialize(injury), status=201)


@bp.get("/employee-health/injury-reports")
def list_injuries():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (lambda i: i["employee_id"] == user_id) if role == "StaffEmployee" else None
    items, meta = list_response(
        store.injuries.values(),
        {
            "employee_id": lambda i: i["employee_id"],
            "exposure_case_id": lambda i: i["exposure_case_id"],
            "status": lambda i: i["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/injury-reports/<rid>")
def get_injury(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    injury = get_or_404(store.injuries, rid)
    staff_scope_check(role, user_id, injury["employee_id"])
    return success_object(serialize(injury))


@bp.post("/employee-health/injury-reports/<rid>/transition")
def transition_injury(rid):
    user_id, role = auth()
    require_role(role, {"SafetyOfficer"})
    injury = get_or_404(store.injuries, rid)
    data = body()
    to_state = data.get("to_state")

    if to_state not in WC_TARGETS:
        raise ApiError("ERR_INVALID_ENUM", "to_state must be one of %s" % sorted(WC_TARGETS))

    status = injury["status"]
    if to_state == "WC_SUBMITTED":
        if status != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Report must be FILED to submit")
        # Claim number: 'WC-' + zero-padded 6-digit sequence in submission order.
        store.wc_sequence += 1
        injury["wc_claim_number"] = "WC-%06d" % store.wc_sequence
    elif to_state in ("WC_ACCEPTED", "WC_DENIED"):
        if status not in ("WC_SUBMITTED", "APPEALED"):
            raise ApiError(
                "ERR_INVALID_STATE", "Report must be WC_SUBMITTED or APPEALED"
            )
    elif to_state == "APPEALED":
        # The deny-and-appeal loop may repeat without bound.
        if status != "WC_DENIED":
            raise ApiError("ERR_INVALID_STATE", "Report must be WC_DENIED to appeal")

    injury["status"] = to_state
    touch(injury)
    return success_object(serialize(injury))
