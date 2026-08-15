"""Campaign participations: list/read plus ADMINISTERED / DECLINED / EXEMPTED."""
from flask import Blueprint

from db import now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from util import parse_dt

bp = Blueprint("participations", __name__)

EXEMPTION_TYPES = {"MEDICAL", "RELIGIOUS"}
PARTICIPATION_TARGETS = {"ADMINISTERED", "DECLINED", "EXEMPTED"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.get("/employee-health/campaign-participations")
def list_participations():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (lambda p: p["employee_id"] == user_id) if role == "StaffEmployee" else None
    items, meta = list_response(
        store.participations.values(),
        {
            "campaign_id": lambda p: p["campaign_id"],
            "employee_id": lambda p: p["employee_id"],
            "status": lambda p: p["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/campaign-participations/<rid>")
def get_participation(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    part = get_or_404(store.participations, rid)
    staff_scope_check(role, user_id, part["employee_id"])
    return success_object(serialize(part))


@bp.post("/employee-health/campaign-participations/<rid>/transition")
def transition_participation(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse", "StaffEmployee", "EmployeeHealthPhysician"})
    data = body()
    to_state = data.get("to_state")

    # Per-transition role authorization (priority 2).
    if to_state == "ADMINISTERED" and role != "EmployeeHealthNurse":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only a nurse may record administration")
    if to_state == "DECLINED" and role != "StaffEmployee":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only the employee themself may decline")
    if to_state == "EXEMPTED" and role != "EmployeeHealthPhysician":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only a physician may exempt")

    part = get_or_404(store.participations, rid)
    campaign = store.campaigns[part["campaign_id"]]
    emp = store.employees[part["employee_id"]]

    if to_state == "DECLINED":
        # Self-scope (priority 3) precedes state legality.
        if user_id != part["employee_id"]:
            raise ApiError(
                "ERR_OWNERSHIP_REQUIRED",
                "Vaccination declination belongs to the employee themself",
            )

    if to_state not in PARTICIPATION_TARGETS:
        raise ApiError(
            "ERR_INVALID_ENUM", "to_state must be one of %s" % sorted(PARTICIPATION_TARGETS)
        )
    if part["status"] != "PENDING":
        raise ApiError("ERR_PARTICIPATION_NOT_PENDING", "Participation is not PENDING")

    if to_state == "ADMINISTERED":
        # Safety gate (priority 7): a suspended employee cannot be vaccinated
        # into compliance; then the temporal window check (priority 9).
        if emp["status"] != "ACTIVE":
            raise ApiError("ERR_EMPLOYEE_NOT_ACTIVE", "Employee is not ACTIVE")
        administered_at = parse_dt(data.get("administered_at"))
        if administered_at is not None and not (
            campaign["window_start"] <= administered_at <= campaign["window_end"]
        ):
            raise ApiError(
                "ERR_ADMINISTER_OUTSIDE_WINDOW",
                "administered_at must lie within the campaign window (inclusive)",
            )
        if administered_at is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "administered_at must be a valid ISO 8601 timestamp",
            )
        part["administered_at"] = administered_at
        part["status"] = "ADMINISTERED"
        touch(part)

    elif to_state == "DECLINED":
        reason = data.get("declination_reason")
        if not isinstance(reason, str) or not reason:
            raise ApiError(
                "ERR_DECLINATION_REASON_REQUIRED",
                "A non-empty declination_reason is required",
            )
        part["declination_reason"] = reason
        part["declined_at"] = now()
        part["status"] = "DECLINED"
        touch(part)

    else:  # EXEMPTED
        exemption_type = check_enum(data.get("exemption_type"), EXEMPTION_TYPES, "exemption_type")
        part["exemption_type"] = exemption_type
        part["status"] = "EXEMPTED"
        touch(part)

    return success_object(serialize(part))
