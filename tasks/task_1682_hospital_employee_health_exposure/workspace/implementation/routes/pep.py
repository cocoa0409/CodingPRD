"""PEP regimens: list/read plus the STARTED / COMPLETED / DECLINED lifecycle."""
from datetime import timedelta

from flask import Blueprint

from db import base_fields, now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.calculations import (PEP_COURSE_DAYS, create_followup,
                                   osha_recordable, recompute_osha_for_case)
from util import parse_dt

bp = Blueprint("pep", __name__)

MEDICATIONS = {"HIV_3DRUG", "HBV_HBIG", "HBV_VACCINE_SERIES"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


def _case_scope(role, user_id, pep):
    case = store.cases[pep["exposure_case_id"]]
    staff_scope_check(role, user_id, case["employee_id"])


@bp.get("/employee-health/pep-regimens")
def list_pep():
    user_id, role = auth()
    require_role(role, _READ_ROLES)

    def scope(p):
        if role != "StaffEmployee":
            return True
        case = store.cases.get(p["exposure_case_id"])
        return case is not None and case["employee_id"] == user_id

    items, meta = list_response(
        store.pep_regimens.values(),
        {
            "exposure_case_id": lambda p: p["exposure_case_id"],
            "status": lambda p: p["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/pep-regimens/<rid>")
def get_pep(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    pep = get_or_404(store.pep_regimens, rid)
    _case_scope(role, user_id, pep)
    return success_object(serialize(pep))


@bp.post("/employee-health/pep-regimens/<rid>/transition")
def transition_pep(rid):
    user_id, role = auth()
    # Endpoint admits physician (STARTED/COMPLETED) and the exposed employee (DECLINED).
    require_role(role, {"EmployeeHealthPhysician", "StaffEmployee"})
    data = body()
    to_state = data.get("to_state")

    # Per-transition role authorization (priority 2) is decidable from to_state.
    if to_state in ("STARTED", "COMPLETED") and role != "EmployeeHealthPhysician":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only a physician may START or COMPLETE PEP")
    if to_state == "DECLINED" and role != "StaffEmployee":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only the exposed employee may decline PEP")

    pep = get_or_404(store.pep_regimens, rid)
    case = store.cases[pep["exposure_case_id"]]

    if to_state == "DECLINED":
        # Employee consent is self-only (priority 2.5/3, before state legality).
        if user_id != case["employee_id"]:
            raise ApiError(
                "ERR_OWNERSHIP_REQUIRED",
                "PEP declination belongs to the exposed employee alone",
            )
        if pep["status"] != "RECOMMENDED":
            raise ApiError("ERR_INVALID_STATE", "PEP regimen is not RECOMMENDED")
        pep["status"] = "DECLINED"
        touch(pep)

    elif to_state == "STARTED":
        if pep["status"] != "RECOMMENDED":
            raise ApiError("ERR_INVALID_STATE", "PEP regimen is not RECOMMENDED")
        # Safety gate: inclusive 72-hour window.
        if now() > pep["window_deadline"]:
            raise ApiError(
                "ERR_PEP_WINDOW_EXPIRED",
                "The 72-hour prophylaxis window has passed",
            )
        # Temporal: first dose no earlier than the exposure, no later than now.
        started_at = parse_dt(data.get("started_at"))
        if started_at is not None and (
            started_at < case["exposure_datetime"] or started_at > now()
        ):
            raise ApiError(
                "ERR_COMPLETION_OUT_OF_RANGE",
                "started_at must be no earlier than the exposure and no later than now",
            )
        # Field shape.
        if started_at is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "started_at must be a valid ISO 8601 timestamp"
            )
        medication = data.get("medication")
        if medication is not None:
            check_enum(medication, MEDICATIONS, "medication")
            pep["medication"] = medication

        pep["started_at"] = started_at
        pep["status"] = "STARTED"
        touch(pep)
        # Serology program: WEEK_6 / WEEK_12 / MONTH_6 appear SCHEDULED.
        for milestone in ("WEEK_6", "WEEK_12", "MONTH_6"):
            create_followup(case, milestone)
        # Workers' compensation linkage: automatic injury report.
        injury = base_fields()
        injury.update(
            {
                "employee_id": case["employee_id"],
                "exposure_case_id": case["id"],
                "injury_type": "NEEDLESTICK",
                "injury_datetime": case["exposure_datetime"],
                "origin": "PEP_LINKAGE",
                "osha_recordable": False,
                "wc_claim_number": None,
                "status": "FILED",
            }
        )
        injury["osha_recordable"] = osha_recordable(injury)
        store.injuries[injury["id"]] = injury
        # Linkage event: recompute flags on reports linked to this case.
        recompute_osha_for_case(case["id"])

    elif to_state == "COMPLETED":
        if pep["status"] != "STARTED":
            raise ApiError("ERR_INVALID_STATE", "PEP regimen is not STARTED")
        # Safety gate: full 28-day course, inclusive boundary.
        if now() < pep["started_at"] + timedelta(days=PEP_COURSE_DAYS):
            raise ApiError(
                "ERR_PEP_COURSE_INCOMPLETE",
                "The 28-day prophylaxis course has not fully elapsed",
            )
        pep["status"] = "COMPLETED"
        touch(pep)
        recompute_osha_for_case(case["id"])

    else:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "to_state must be one of ['COMPLETED', 'DECLINED', 'STARTED']",
        )

    return success_object(serialize(pep))
