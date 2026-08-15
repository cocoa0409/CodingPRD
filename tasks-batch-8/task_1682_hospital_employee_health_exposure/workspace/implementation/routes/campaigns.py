"""Vaccination campaigns: create, open (fan-out), close (delinquency cascade), coverage."""
from flask import Blueprint

from db import base_fields, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404
from services.calculations import campaign_coverage
from services.core import create_hold
from util import parse_dt

bp = Blueprint("campaigns", __name__)

VACCINE_TYPES = {"INFLUENZA", "COVID", "HEP_B", "TDAP"}
CAMPAIGN_TARGETS = {"OPEN", "CLOSED"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}
_COVERAGE_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer", "SafetyOfficer",
}


@bp.post("/employee-health/vaccination-campaigns")
def create_campaign():
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    data = body()

    vaccine_type = data.get("vaccine_type")
    window_start = parse_dt(data.get("window_start"))
    window_end = parse_dt(data.get("window_end"))

    # Uniqueness/overlap (priority 10): same-vaccine CLOSED windows may not
    # intersect or even touch.
    if vaccine_type in VACCINE_TYPES and window_start is not None and window_end is not None:
        for other in store.campaigns.values():
            if other["vaccine_type"] != vaccine_type:
                continue
            if window_start <= other["window_end"] and window_end >= other["window_start"]:
                raise ApiError(
                    "ERR_CAMPAIGN_WINDOW_OVERLAP",
                    "Same-vaccine campaign windows may not intersect or touch",
                )

    # Field shape.
    check_enum(vaccine_type, VACCINE_TYPES, "vaccine_type")
    if window_start is None:
        raise ApiError("ERR_INVALID_REQUEST", "window_start must be a valid ISO 8601 timestamp")
    if window_end is None:
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be a valid ISO 8601 timestamp")
    if window_end < window_start:
        raise ApiError("ERR_INVALID_REQUEST", "window_end must not be earlier than window_start")
    department_scope = data.get("department_scope")
    if (
        not isinstance(department_scope, list)
        or not department_scope
        or not all(isinstance(d, str) and d for d in department_scope)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            'department_scope must be a non-empty list of department codes or ["ALL"]',
        )

    campaign = base_fields()
    campaign.update(
        {
            "vaccine_type": vaccine_type,
            "window_start": window_start,
            "window_end": window_end,
            "department_scope": list(department_scope),
            "status": "PLANNED",
        }
    )
    store.campaigns[campaign["id"]] = campaign
    return success_object(serialize(campaign), status=201)


@bp.get("/employee-health/vaccination-campaigns")
def list_campaigns():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    items, meta = list_response(
        store.campaigns.values(),
        {
            "vaccine_type": lambda c: c["vaccine_type"],
            "status": lambda c: c["status"],
        },
    )
    return success_list(items, meta)


@bp.get("/employee-health/vaccination-campaigns/<rid>")
def get_campaign(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    campaign = get_or_404(store.campaigns, rid)
    return success_object(serialize(campaign))


@bp.post("/employee-health/vaccination-campaigns/<rid>/transition")
def transition_campaign(rid):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    campaign = get_or_404(store.campaigns, rid)
    data = body()
    to_state = data.get("to_state")

    if campaign["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Campaign is CLOSED")

    if to_state == "OPEN":
        if campaign["status"] != "PLANNED":
            raise ApiError("ERR_INVALID_STATE", "Campaign must be PLANNED to open")
        campaign["status"] = "OPEN"
        touch(campaign)
        # Fan-out: one PENDING participation per in-scope ACTIVE employee,
        # deterministic order: created_at ASC, tie-break employee_ref ASC.
        in_scope = set(campaign["department_scope"])
        employees = [
            e
            for e in store.employees.values()
            if e["status"] == "ACTIVE"
            and ("ALL" in in_scope or e["department"] in in_scope)
        ]
        employees.sort(key=lambda e: (e["created_at"], e["employee_ref"]))
        for emp in employees:
            part = base_fields()
            part.update(
                {
                    "campaign_id": campaign["id"],
                    "employee_id": emp["id"],
                    "status": "PENDING",
                    "administered_at": None,
                    "declined_at": None,
                    "declination_reason": None,
                    "exemption_type": None,
                }
            )
            store.participations[part["id"]] = part

    elif to_state == "CLOSED":
        if campaign["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Campaign must be OPEN to close")
        # The CLOSED window [window_start, window_end] must have fully elapsed (STRICT).
        from db import now

        if now() <= campaign["window_end"]:
            raise ApiError(
                "ERR_CAMPAIGN_WINDOW_NOT_ENDED",
                "The campaign window has not fully elapsed",
            )
        campaign["status"] = "CLOSED"
        touch(campaign)
        # CASCADE A: delinquency -> hold -> suspension, in enrollment order.
        pending = [
            p
            for p in store.participations.values()
            if p["campaign_id"] == campaign["id"] and p["status"] == "PENDING"
        ]
        pending.sort(key=lambda p: p["_seq"])
        for part in pending:
            part["status"] = "DELINQUENT"
            touch(part)
            create_hold(
                part["employee_id"], "CAMPAIGN_DELINQUENT", participation_id=part["id"]
            )
    else:
        raise ApiError(
            "ERR_INVALID_ENUM", "to_state must be one of %s" % sorted(CAMPAIGN_TARGETS)
        )

    return success_object(serialize(campaign))


@bp.get("/employee-health/vaccination-campaigns/<rid>/coverage")
def get_coverage(rid):
    user_id, role = auth()
    require_role(role, _COVERAGE_ROLES)
    campaign = get_or_404(store.campaigns, rid)
    return success_object(campaign_coverage(campaign))
