"""Instructors, continuing education and certification renewal (PRD §3.5)."""

from flask import Blueprint, request

from core import numbers as N
from core import timeutil as T
from core.constants import (
    CERT_LEVELS,
    CERT_RENEWAL_CE_HOURS,
    CERT_VALIDITY_DAYS,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, endpoint, pagination, paginate, query_enum, validate_body,
)
from core.lookups import resource_or_404
from core.store import all_rows, new_row, touch
from domain import derive, serialize

bp = Blueprint("instructors", __name__)

CERT_STATUSES = ["CURRENT", "GRACE", "LAPSED", "SUSPENDED"]


@bp.post("/instructors")
@endpoint(["ProgramAdmin"])
def create_instructor():
    payload = validate_body([
        Field("full_name", "string", required=True),
        Field("certification_level", "enum", required=True, members=CERT_LEVELS),
        Field("certification_expires_at", "instant", required=True),
        Field("supervisor_instructor_id", "string"),
    ])
    supervisor_id = payload.get("supervisor_instructor_id")
    # Adjudication of friction 2 (§3.5): a trainee registered WITHOUT a supervisor
    # is refused with ERR_VALIDATION (400), i.e. as a conditionally required body
    # field at rung 6/7, NOT with ERR_SUPERVISOR_REQUIRED.  The ladder scopes
    # rung 25 to session creation only; widening that rung's scope here would
    # invent a rung the ladder does not declare, whereas the required-field
    # reading leaves every declared rung reachable exactly where it is declared.
    if payload["certification_level"] == "IN_TRAINING" and not supervisor_id:
        fail("ERR_VALIDATION",
             "supervisor_instructor_id is required for an IN_TRAINING instructor.")
    if payload["certification_level"] != "IN_TRAINING" and supervisor_id:
        fail("ERR_VALIDATION",
             "supervisor_instructor_id must be omitted unless the instructor is "
             "IN_TRAINING.")
    if supervisor_id:
        resource_or_404("instructors", supervisor_id)          # rung 13

    row = new_row("instructors")
    row.update({
        "full_name": payload["full_name"],
        "certification_level": payload["certification_level"],
        # §2.5 class 2: caller-supplied at registration, echoed byte for byte.
        "certification_expires_at": T.echoed(payload["certification_expires_at"]),
        "supervisor_instructor_id": supervisor_id or None,
        "ce_hours_accrued": 0,
        "suspended_until": None,
        "_suspension_incident_id": None,
    })
    return object_response(serialize.instructor(row), 201)


@bp.get("/instructors/<instructor_id>")
@endpoint(["ProgramAdmin", "Instructor", "VolunteerCoordinator"])
def read_instructor(instructor_id):
    return object_response(serialize.instructor(
        resource_or_404("instructors", instructor_id)))


@bp.get("/instructors")
@endpoint(["ProgramAdmin", "Instructor"])
def list_instructors():
    limit, offset = pagination()
    status = query_enum("certification_status", CERT_STATUSES)
    level = query_enum("certification_level", CERT_LEVELS)
    supervisor_id = request.args.get("supervisor_instructor_id")
    rows = all_rows("instructors")
    if level is not None:
        rows = [r for r in rows if r["certification_level"] == level]
    if supervisor_id is not None:
        rows = [r for r in rows if r.get("supervisor_instructor_id") == supervisor_id]
    if status is not None:
        rows = [r for r in rows if derive.certification_status(r) == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.instructor(r) for r in page],
                         limit, offset, len(rows))


@bp.post("/instructors/<instructor_id>/ce-hours")
@endpoint(["ProgramAdmin"])
def accrue_ce_hours(instructor_id):
    payload = validate_body([
        Field("hours", "number", required=True, exclusive_min=0),
        Field("completed_on", "date", required=True),
    ])
    row = resource_or_404("instructors", instructor_id)
    total = N.dec(row["ce_hours_accrued"]) + N.dec(payload["hours"])
    row["ce_hours_accrued"] = float(total) if total != total.to_integral_value() \
        else int(total)
    touch(row)
    return object_response(serialize.instructor(row))


@bp.post("/instructors/<instructor_id>/renew-certification")
@endpoint(["ProgramAdmin"])
def renew_certification(instructor_id):
    payload = validate_body([Field("renewed_on", "date", required=True)])
    row = resource_or_404("instructors", instructor_id)
    if derive.certification_status(row) not in ("GRACE", "LAPSED"):   # rung 19
        fail("ERR_INVALID_STATE",
             "Only a GRACE or LAPSED certification may be renewed.")
    if row["ce_hours_accrued"] < CERT_RENEWAL_CE_HOURS:               # rung 43
        fail("ERR_CE_HOURS_INSUFFICIENT",
             "At least %d continuing-education hours are required."
             % CERT_RENEWAL_CE_HOURS)
    renewed_on = T.parse_date(payload["renewed_on"])
    # §2.5: after a renewal certification_expires_at is a DERIVED instant and is
    # therefore rendered with three fractional digits, unlike the caller-supplied
    # value echoed at registration.
    row["certification_expires_at"] = T.derived(T.plus_days(
        T.date_to_instant(renewed_on), CERT_VALIDITY_DAYS))
    row["ce_hours_accrued"] = 0
    touch(row)
    return object_response(serialize.instructor(row))
