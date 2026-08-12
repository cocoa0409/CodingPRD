"""Volunteers, qualifications and the service-hours ledger (PRD §3.4)."""

from flask import Blueprint, request

from core import timeutil as T
from core.constants import (
    CREW_ROLES_QUALIFICATION,
    CREW_ROLE_MIN_AGE,
    CREW_ROLE_MIN_TRAINING_HOURS,
    QUALIFICATION_VALIDITY_DAYS,
    VOLUNTEER_RETRAINING_INTERVAL_DAYS,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, endpoint, pagination, paginate, query_enum, validate_body,
)
from core.lookups import resource_or_404
from core.store import all_rows, new_row, touch
from domain import derive, reports, serialize

bp = Blueprint("volunteers", __name__)

QUALIFICATION_STATUSES = ["IN_TRAINING", "QUALIFIED", "EXPIRED", "SUSPENDED"]
SERVICE_HOUR_VARIANTS = ["scheduled", "delivered"]


def volunteer_or_404(volunteer_id):
    return resource_or_404("volunteers", volunteer_id)


@bp.post("/volunteers")
@endpoint(["VolunteerCoordinator", "ProgramAdmin"])
def create_volunteer():
    payload = validate_body([
        Field("full_name", "string", required=True),
        Field("date_of_birth", "date", required=True),
        Field("last_retraining_on", "date", required=True),
    ])
    last_retraining = T.parse_date(payload["last_retraining_on"])
    row = new_row("volunteers")
    row.update({
        "full_name": payload["full_name"],
        "date_of_birth": payload["date_of_birth"],
        "last_retraining_on": payload["last_retraining_on"],
        "retraining_due_at": T.derived(T.plus_days(
            T.date_to_instant(last_retraining), VOLUNTEER_RETRAINING_INTERVAL_DAYS)),
        "suspended_until": None,
        "suspension_reason": None,
        "_suspension_incident_id": None,
    })
    return object_response(serialize.volunteer(row), 201)


@bp.get("/volunteers/<volunteer_id>")
@endpoint(["VolunteerCoordinator", "ProgramAdmin", "Instructor"])
def read_volunteer(volunteer_id):
    return object_response(serialize.volunteer(volunteer_or_404(volunteer_id)))


@bp.post("/volunteers/<volunteer_id>/qualifications")
@endpoint(["VolunteerCoordinator", "ProgramAdmin"])
def create_qualification(volunteer_id):
    payload = validate_body([
        Field("crew_role", "enum", required=True, members=CREW_ROLES_QUALIFICATION),
        Field("training_hours", "number", required=True, minimum=0),
    ])
    volunteer_or_404(volunteer_id)
    row = new_row("volunteer_qualifications")
    row.update({
        "volunteer_id": volunteer_id,
        "crew_role": payload["crew_role"],
        "training_hours": payload["training_hours"],
        "signed_off_on": None,
        "expires_at": None,
    })
    return object_response(serialize.qualification(row), 201)


@bp.get("/volunteer-qualifications")
@endpoint(["VolunteerCoordinator", "ProgramAdmin", "Instructor"])
def list_qualifications():
    limit, offset = pagination()
    status = query_enum("status", QUALIFICATION_STATUSES)
    crew_role = query_enum("crew_role", CREW_ROLES_QUALIFICATION)
    volunteer_id = request.args.get("volunteer_id")
    rows = all_rows("volunteer_qualifications")
    if volunteer_id is not None:
        rows = [r for r in rows if r["volunteer_id"] == volunteer_id]
    if crew_role is not None:
        rows = [r for r in rows if r["crew_role"] == crew_role]
    if status is not None:
        rows = [r for r in rows if derive.qualification_status(r) == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.qualification(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/volunteer-qualifications/<qualification_id>")
@endpoint(["VolunteerCoordinator", "ProgramAdmin"])
def read_qualification(qualification_id):
    row = resource_or_404("volunteer_qualifications", qualification_id)
    return object_response(serialize.qualification(row))


@bp.post("/volunteer-qualifications/<qualification_id>/sign-off")
@endpoint(["VolunteerCoordinator", "ProgramAdmin"])
def sign_off(qualification_id):
    payload = validate_body([Field("signed_off_on", "date", required=True)])
    row = resource_or_404("volunteer_qualifications", qualification_id)
    volunteer = volunteer_or_404(row["volunteer_id"])
    if derive.qualification_status(row) != "IN_TRAINING":     # rung 19
        fail("ERR_INVALID_STATE", "Only an IN_TRAINING qualification may be signed off.")
    role = row["crew_role"]
    if derive.age_years(volunteer["date_of_birth"]) < CREW_ROLE_MIN_AGE[role]:
        fail("ERR_VOLUNTEER_UNDER_AGE",                        # rung 37
             "The volunteer is below the minimum age for %s." % role)
    if row["training_hours"] < CREW_ROLE_MIN_TRAINING_HOURS[role]:
        fail("ERR_VOLUNTEER_NOT_QUALIFIED",                    # rung 38
             "Logged training hours are below the %s minimum." % role)
    signed_off_on = T.parse_date(payload["signed_off_on"])
    row["signed_off_on"] = payload["signed_off_on"]
    row["expires_at"] = T.derived(T.plus_days(T.date_to_instant(signed_off_on),
                                              QUALIFICATION_VALIDITY_DAYS))
    touch(row)
    return object_response(serialize.qualification(row))


@bp.post("/volunteers/<volunteer_id>/retraining")
@endpoint(["VolunteerCoordinator", "ProgramAdmin"])
def retraining(volunteer_id):
    payload = validate_body([Field("completed_on", "date", required=True)])
    row = volunteer_or_404(volunteer_id)
    # Adjudication of friction 1 (§3.4): re-training recorded against a volunteer
    # who is NOT INACTIVE is ACCEPTED as an ordinary refresh, because the stated
    # purpose of the operation includes re-signing EXPIRED qualifications, and a
    # qualification expires on its own 365-day clock while the volunteer is still
    # ACTIVE.  Refusing with ERR_INVALID_STATE would make that declared behaviour
    # unreachable, so this reading keeps the larger set of behaviours reachable.
    expired = [q for q in derive.volunteer_qualifications(volunteer_id)
               if derive.qualification_status(q) == "EXPIRED"]
    completed_on = T.parse_date(payload["completed_on"])
    row["last_retraining_on"] = payload["completed_on"]
    row["retraining_due_at"] = T.derived(T.plus_days(
        T.date_to_instant(completed_on), VOLUNTEER_RETRAINING_INTERVAL_DAYS))
    touch(row)
    for qualification in expired:
        qualification["signed_off_on"] = payload["completed_on"]
        qualification["expires_at"] = T.derived(T.plus_days(
            T.date_to_instant(completed_on), QUALIFICATION_VALIDITY_DAYS))
        touch(qualification)
    return object_response(serialize.volunteer(row))


@bp.get("/volunteers/<volunteer_id>/service-hours")
@endpoint(["VolunteerCoordinator", "ProgramAdmin"])
def service_hours(volunteer_id):
    raw_start = request.args.get("period_start")
    raw_end = request.args.get("period_end")
    variant = request.args.get("variant")
    if raw_start is None or raw_end is None or variant is None:
        # §2.9: variant has NO default on this endpoint - omitting it is 400.
        fail("ERR_VALIDATION", "period_start, period_end and variant are required.")
    period_start = T.parse_date(raw_start)
    period_end = T.parse_date(raw_end)
    if period_start is None or period_end is None:
        fail("ERR_VALIDATION", "period_start and period_end must be YYYY-MM-DD dates.")
    if period_end < period_start:
        fail("ERR_VALIDATION", "period_end must not precede period_start.")
    if variant not in SERVICE_HOUR_VARIANTS:
        fail("ERR_VALIDATION", "Unsupported variant %r." % variant)
    volunteer_or_404(volunteer_id)
    hours, count = reports.volunteer_service_hours(volunteer_id, period_start,
                                                   period_end, variant)
    return object_response({
        "volunteer_id": volunteer_id,
        "period_start": raw_start,
        "period_end": raw_end,
        "variant": variant,
        "service_hours": hours,
        "session_count": count,
    })
