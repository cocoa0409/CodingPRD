"""Serology follow-ups: list/read plus RESULTED (nurse) and WAIVED (physician)."""
from flask import Blueprint

from db import now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.core import create_restriction
from util import parse_dt

bp = Blueprint("serology", __name__)

FOLLOWUP_RESULTS = {"NEGATIVE", "POSITIVE", "INDETERMINATE"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


def _case_of(fu):
    return store.cases.get(fu["exposure_case_id"])


@bp.get("/employee-health/serology-follow-ups")
def list_followups():
    user_id, role = auth()
    require_role(role, _READ_ROLES)

    def scope(f):
        if role != "StaffEmployee":
            return True
        case = _case_of(f)
        return case is not None and case["employee_id"] == user_id

    items, meta = list_response(
        store.followups.values(),
        {
            "exposure_case_id": lambda f: f["exposure_case_id"],
            "status": lambda f: f["status"],
            "milestone": lambda f: f["milestone"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/serology-follow-ups/<rid>")
def get_followup(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    fu = get_or_404(store.followups, rid)
    case = _case_of(fu)
    if role == "StaffEmployee":
        staff_scope_check(role, user_id, case["employee_id"])
    return success_object(serialize(fu))


@bp.post("/employee-health/serology-follow-ups/<rid>/transition")
def transition_followup(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse", "EmployeeHealthPhysician"})
    data = body()
    to_state = data.get("to_state")

    # Per-transition role authorization: RESULTED is the nurse's, WAIVED the physician's.
    if to_state == "RESULTED" and role != "EmployeeHealthNurse":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only a nurse may result a follow-up")
    if to_state == "WAIVED" and role != "EmployeeHealthPhysician":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only a physician may waive a follow-up")

    fu = get_or_404(store.followups, rid)
    case = _case_of(fu)

    if to_state not in ("RESULTED", "WAIVED"):
        raise ApiError("ERR_INVALID_ENUM", "to_state must be RESULTED or WAIVED")

    # State legality: resulting or waiving requires DUE or OVERDUE.
    if fu["status"] not in ("DUE", "OVERDUE"):
        raise ApiError("ERR_FOLLOWUP_NOT_DUE", "Follow-up is not DUE or OVERDUE")

    if to_state == "RESULTED":
        # Temporal: resulted_at within [exposure_datetime, now].
        resulted_at = parse_dt(data.get("resulted_at"))
        if resulted_at is not None and (
            resulted_at > now() or resulted_at < case["exposure_datetime"]
        ):
            raise ApiError(
                "ERR_COMPLETION_OUT_OF_RANGE",
                "resulted_at must be no earlier than the exposure and no later than now",
            )
        # Field shape.
        result = check_enum(data.get("result"), FOLLOWUP_RESULTS, "result")
        if resulted_at is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "resulted_at must be a valid ISO 8601 timestamp"
            )
        fu["result"] = result
        fu["resulted_at"] = resulted_at
        fu["status"] = "RESULTED"
        touch(fu)

        # CASCADE B: a POSITIVE result on a post-baseline milestone seroconverts.
        if result == "POSITIVE" and fu["milestone"] != "BASELINE":
            if case["case_status"] in ("REPORTED", "EVALUATION", "MANAGEMENT"):
                case["case_status"] = "SEROCONVERTED"
                touch(case)
                # Automatic open-ended FULL_EXCLUSION from the result instant.
                create_restriction(
                    case["employee_id"],
                    "FULL_EXCLUSION",
                    resulted_at,
                    None,
                    "SEROCONVERSION",
                    exposure_case_id=case["id"],
                )
    else:  # WAIVED
        reason = data.get("reason")
        if not isinstance(reason, str) or len(reason) < 10:
            raise ApiError(
                "ERR_INSUFFICIENT_JUSTIFICATION",
                "A waive reason of at least 10 characters is required",
            )
        fu["status"] = "WAIVED"
        touch(fu)

    return success_object(serialize(fu))
