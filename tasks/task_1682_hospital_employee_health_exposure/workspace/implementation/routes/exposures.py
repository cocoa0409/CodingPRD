"""Exposure cases: intake, clinical transitions, source-patient testing."""
from flask import Blueprint

from db import base_fields, now, serialize, store, touch
from errors import ApiError
from middleware import (auth, body, check_bool, check_enum, list_response,
                        require_role)
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.calculations import (classify_exposure, create_followup,
                                   create_pep_regimen)
from util import parse_dt

bp = Blueprint("exposures", __name__)

EXPOSURE_TYPES = {"PERCUTANEOUS", "MUCOUS_MEMBRANE", "SKIN_CONTACT", "BITE"}
BODY_FLUIDS = {"BLOOD", "OTHER_POTENTIALLY_INFECTIOUS", "NON_INFECTIOUS"}
CONSENT_OUTCOMES = {"CONSENT_GRANTED", "CONSENT_DECLINED", "WAIVED_UNABLE"}
SOURCE_RESULTS = {"NEGATIVE", "POSITIVE", "INDETERMINATE"}
CASE_TARGETS = {"EVALUATION", "MANAGEMENT", "CLOSED"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.post("/employee-health/employees/<emp_id>/exposure-cases")
def create_case(emp_id):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    emp = get_or_404(store.employees, emp_id)
    data = body()

    # Referential coherence: source_patient_ref present iff source_known.
    source_known = data.get("source_known")
    source_ref = data.get("source_patient_ref")
    if source_known is True:
        if not isinstance(source_ref, str) or not source_ref:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "source_patient_ref is required when source_known is true",
            )
    elif source_known is False:
        if source_ref is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "source_patient_ref must be null when source_known is false",
            )

    # Temporal: exposure_datetime must not be after the current logical clock time.
    exposure_dt = parse_dt(data.get("exposure_datetime"))
    if exposure_dt is not None and exposure_dt > now():
        raise ApiError(
            "ERR_COMPLETION_OUT_OF_RANGE",
            "exposure_datetime must not be after the current time",
        )

    # Field shape.
    exposure_type = check_enum(data.get("exposure_type"), EXPOSURE_TYPES, "exposure_type")
    body_fluid = check_enum(data.get("body_fluid"), BODY_FLUIDS, "body_fluid")
    check_bool(source_known, "source_known")
    if exposure_dt is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "exposure_datetime must be a valid ISO 8601 timestamp"
        )

    risk = classify_exposure(exposure_type, body_fluid, source_known)
    pep_required = risk in ("HIGH", "MEDIUM")

    case = base_fields()
    case.update(
        {
            "employee_id": emp["id"],
            "exposure_type": exposure_type,
            "exposure_datetime": exposure_dt,
            "reported_at": now(),
            "source_known": source_known,
            "source_patient_ref": source_ref if source_known else None,
            "body_fluid": body_fluid,
            "risk_classification": risk,
            "case_status": "REPORTED",
            "source_test_status": "CONSENT_PENDING" if source_known else "NOT_REQUIRED",
            "pep_required": pep_required,
            "hiv_result": "PENDING",
            "hbv_result": "PENDING",
            "hcv_result": "PENDING",
            "source_resulted_at": None,
            "recorded_by_user_id": user_id,
            "consent_recorded_by_user_id": None,
        }
    )
    store.cases[case["id"]] = case
    # Intake auto-creations per exposure_risk_classification.
    if pep_required:
        create_pep_regimen(case, medication="HIV_3DRUG")
    create_followup(case, "BASELINE")
    return success_object(serialize(case), status=201)


@bp.get("/employee-health/exposure-cases")
def list_cases():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (lambda c: c["employee_id"] == user_id) if role == "StaffEmployee" else None
    items, meta = list_response(
        store.cases.values(),
        {
            "employee_id": lambda c: c["employee_id"],
            "case_status": lambda c: c["case_status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/exposure-cases/<rid>")
def get_case(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    case = get_or_404(store.cases, rid)
    staff_scope_check(role, user_id, case["employee_id"])
    return success_object(serialize(case))


@bp.post("/employee-health/exposure-cases/<rid>/transition")
def transition_case(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthPhysician"})
    case = get_or_404(store.cases, rid)
    data = body()
    to_state = data.get("to_state")

    # Terminal states admit no clinical advance.
    if case["case_status"] in ("CLOSED", "SEROCONVERTED"):
        raise ApiError("ERR_INVALID_STATE", "Case is in a terminal state")

    if to_state == "EVALUATION":
        if case["case_status"] != "REPORTED":
            raise ApiError("ERR_INVALID_STATE", "Case must be REPORTED to enter EVALUATION")
    elif to_state == "MANAGEMENT":
        if case["case_status"] != "EVALUATION":
            raise ApiError("ERR_INVALID_STATE", "Case must be EVALUATION to enter MANAGEMENT")
        if case["source_test_status"] not in (
            "NOT_REQUIRED", "RESULTED", "CONSENT_DECLINED", "WAIVED_UNABLE"
        ):
            raise ApiError(
                "ERR_SOURCE_TESTING_UNRESOLVED",
                "Source testing must be resolved before management begins",
            )
    elif to_state == "CLOSED":
        if case["case_status"] != "MANAGEMENT":
            raise ApiError("ERR_INVALID_STATE", "Case must be MANAGEMENT to close")
        open_followup = any(
            f["exposure_case_id"] == case["id"]
            and f["status"] in ("SCHEDULED", "DUE", "OVERDUE")
            for f in store.followups.values()
        )
        unresolved_pep = any(
            p["exposure_case_id"] == case["id"]
            and p["status"] not in ("COMPLETED", "DECLINED", "WINDOW_EXPIRED")
            for p in store.pep_regimens.values()
        )
        active_restriction = any(
            r["exposure_case_id"] == case["id"] and r["status"] == "ACTIVE"
            for r in store.restrictions.values()
        )
        if open_followup or unresolved_pep or active_restriction:
            raise ApiError(
                "ERR_CASE_CLOSE_BLOCKED",
                "Case close blocked by open follow-ups, unresolved PEP, or an ACTIVE restriction",
            )
    else:
        raise ApiError(
            "ERR_INVALID_ENUM", "to_state must be one of %s" % sorted(CASE_TARGETS)
        )

    case["case_status"] = to_state
    touch(case)
    return success_object(serialize(case))


@bp.post("/employee-health/exposure-cases/<rid>/source-testing")
def source_testing(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse"})
    case = get_or_404(store.cases, rid)
    data = body()
    action = data.get("action")

    if action == "RECORD_CONSENT":
        # Segregation of duties (priority 2.5) precedes state legality.
        if user_id == case["recorded_by_user_id"]:
            raise ApiError(
                "ERR_SOD_SOURCE_CONSENT",
                "The intake recorder may not record the source patient's consent",
            )
        if case["source_test_status"] != "CONSENT_PENDING":
            raise ApiError("ERR_INVALID_STATE", "Source testing is not CONSENT_PENDING")
        outcome = check_enum(data.get("outcome"), CONSENT_OUTCOMES, "outcome")
        case["source_test_status"] = outcome
        case["consent_recorded_by_user_id"] = user_id
        touch(case)
    elif action == "RECORD_RESULT":
        if case["source_test_status"] != "CONSENT_GRANTED":
            raise ApiError("ERR_INVALID_STATE", "Source testing is not CONSENT_GRANTED")
        # Temporal precedes field shape (priority 9 before 11).
        source_resulted_at = parse_dt(data.get("source_resulted_at"))
        if source_resulted_at is not None and source_resulted_at > now():
            raise ApiError(
                "ERR_FUTURE_RESULT_DATE",
                "source_resulted_at must not be after the current time",
            )
        hiv = check_enum(data.get("hiv_result"), SOURCE_RESULTS, "hiv_result")
        hbv = check_enum(data.get("hbv_result"), SOURCE_RESULTS, "hbv_result")
        hcv = check_enum(data.get("hcv_result"), SOURCE_RESULTS, "hcv_result")
        if source_resulted_at is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "source_resulted_at must be a valid ISO 8601 timestamp",
            )
        case["hiv_result"] = hiv
        case["hbv_result"] = hbv
        case["hcv_result"] = hcv
        case["source_resulted_at"] = source_resulted_at
        case["source_test_status"] = "RESULTED"
        if hiv == "POSITIVE":
            case["pep_required"] = True
        touch(case)
        # HIV POSITIVE with no regimen yet: auto-create RECOMMENDED; the deadline
        # recomputed from exposure_datetime may already lie in the past.
        if hiv == "POSITIVE":
            if not any(p["exposure_case_id"] == case["id"] for p in store.pep_regimens.values()):
                create_pep_regimen(case, medication="HIV_3DRUG")
    else:
        raise ApiError("ERR_INVALID_ENUM", "action must be RECORD_CONSENT or RECORD_RESULT")

    return success_object(serialize(case))
