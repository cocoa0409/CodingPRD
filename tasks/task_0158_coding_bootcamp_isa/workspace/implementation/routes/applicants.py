"""Applicant funnel (PRD §3.2)."""
from flask import Blueprint, request

import errors
from db import db, stamp_create, touch, clock_iso
from middleware import require_role
from response import success
from services import serialize
from services.common import (
    get_json_body, parse_pagination, sort_by_created, paginate, lookup,
    require_fields, as_int, as_str,
)
from services.derive import seats_committed

bp = Blueprint("applicants", __name__)


@bp.post("/applicants")
def create_applicant():
    require_role("AdmissionsOfficer", "Student")
    body = get_json_body()
    require_fields(body, ["cohort_id", "full_name", "email", "reported_prior_income_cents"])
    cohort_id = as_str(body, "cohort_id")
    # existence of body-referenced parent first (PRD §2.6)
    lookup(db.cohorts, cohort_id)
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    income = as_int(body, "reported_prior_income_cents", min_value=0)

    a = {
        "cohort_id": cohort_id,
        "full_name": full_name,
        "email": email,
        "reported_prior_income_cents": income,
        "status": "APPLIED",
        "admitted_at": None,
    }
    stamp_create(a)
    db.applicants[a["id"]] = a
    return success(serialize.applicant_view(a), status=201)


@bp.get("/applicants/<aid>")
def get_applicant(aid):
    require_role("AdmissionsOfficer", "Student")
    a = lookup(db.applicants, aid)
    return success(serialize.applicant_view(a))


@bp.get("/applicants")
def list_applicants():
    require_role("AdmissionsOfficer")
    limit, offset = parse_pagination()
    cohort_id = request.args.get("cohort_id")
    status = request.args.get("status")
    rows = list(db.applicants.values())
    if cohort_id is not None:
        rows = [a for a in rows if a["cohort_id"] == cohort_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.applicant_view(a) for a in window], pagination=pg)


@bp.post("/applicants/<aid>/admit")
def admit_applicant(aid):
    require_role("AdmissionsOfficer")
    a = lookup(db.applicants, aid)
    if a["status"] != "APPLIED":
        raise errors.invalid_state(f"Applicant is {a['status']}, expected APPLIED")
    cohort = db.cohorts.get(a["cohort_id"])
    # cohort must be OPEN and have a free seat
    if cohort is None or cohort["status"] != "OPEN":
        raise errors.invalid_state("Cohort is not OPEN for admissions")
    committed = seats_committed(cohort["id"])
    if cohort["capacity"] - committed < 1:
        raise errors.ApiError(errors.ERR_COHORT_FULL, 409, "Cohort has no available seat")
    a["status"] = "ADMITTED"
    a["admitted_at"] = clock_iso()
    touch(a)
    return success(serialize.applicant_view(a))


@bp.post("/applicants/<aid>/reject")
def reject_applicant(aid):
    require_role("AdmissionsOfficer")
    a = lookup(db.applicants, aid)
    if a["status"] != "APPLIED":
        raise errors.invalid_state(f"Applicant is {a['status']}, expected APPLIED")
    a["status"] = "REJECTED"
    touch(a)
    return success(serialize.applicant_view(a))


@bp.post("/applicants/<aid>/withdraw")
def withdraw_applicant(aid):
    require_role("AdmissionsOfficer", "Student")
    a = lookup(db.applicants, aid)
    if a["status"] != "ADMITTED":
        raise errors.invalid_state(f"Applicant is {a['status']}, expected ADMITTED")
    # only while no enrollment exists for this applicant
    has_enrollment = any(e["applicant_id"] == aid for e in db.enrollments.values())
    if has_enrollment:
        raise errors.invalid_state("An enrollment already exists for this applicant")
    a["status"] = "WITHDRAWN_APP"
    touch(a)
    return success(serialize.applicant_view(a))
