"""Review assignments: the reviewer calendar (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint

import db
import response
import serializers
import validators as v
from constants import (
    ALL_ROLES, ASSIGNMENT_STATUSES, REVIEWABLE_STATUSES, REVIEW_BUFFER_HOURS,
    ROLE_ANALYST,
)
from errors import (
    ERR_APPLICATION_NOT_REVIEWABLE, ERR_EVALUATOR_CAPACITY_EXCEEDED,
    ERR_EVALUATOR_INACTIVE, ERR_EVALUATOR_PROFESSION_MISMATCH,
    ERR_EVALUATOR_SLOT_CONFLICT, ERR_STALE_VERSION, fail, invalid,
)
from middleware import authenticate
from services import calculations, lookups

bp = Blueprint("assignments", __name__)

BUFFER = timedelta(hours=REVIEW_BUFFER_HOURS)


@bp.post("/licensure/review-assignments")
def create_assignment():
    authenticate([ROLE_ANALYST])
    body = v.body()
    evaluator_id = v.f_string(body, "evaluator_id")
    application_id = v.f_string(body, "application_id")
    window_start_at = v.f_datetime(body, "window_start_at")
    window_end_at = v.f_datetime(body, "window_end_at")
    expected_evaluator_version = v.f_int(body, "expected_evaluator_version")
    if window_end_at <= window_start_at:
        invalid("window_end_at must be strictly after window_start_at.")

    evaluator = lookups.evaluator(evaluator_id)
    application = lookups.application(application_id)

    # Check 7 — stale-view rejection on the capacity-bearing evaluator row.
    if expected_evaluator_version != evaluator["version"]:
        fail(ERR_STALE_VERSION,
             "The evaluator has moved on; expected version %s but found %s."
             % (expected_evaluator_version, evaluator["version"]))

    if application["status"] not in REVIEWABLE_STATUSES:
        fail(ERR_APPLICATION_NOT_REVIEWABLE,
             "The application is in status %s, which this operation does not "
             "permit." % application["status"])

    profession = db.professions[application["profession_id"]]
    if evaluator["profession_code"] != profession["profession_code"]:
        fail(ERR_EVALUATOR_PROFESSION_MISMATCH,
             "The evaluator is not credentialed for this profession.")
    if evaluator["status"] != "ACTIVE":
        fail(ERR_EVALUATOR_INACTIVE, "Only an ACTIVE evaluator may be booked.")

    # Check 31 — closed interval inflated by a 24-hour rest buffer on each side,
    # so touching windows (and windows exactly 24 hours apart) do collide.
    for other in db.assignments.values():
        if other["evaluator_id"] != evaluator["id"] or other["status"] != "ASSIGNED":
            continue
        if ((window_start_at - BUFFER) <= other["window_end_at"]
                and other["window_start_at"] <= (window_end_at + BUFFER)):
            fail(ERR_EVALUATOR_SLOT_CONFLICT,
                 "The requested window collides with an existing assignment, "
                 "including its mandatory 24-hour rest buffer.")

    open_count = calculations.open_assignment_count(evaluator["id"])
    if open_count + 1 > evaluator["max_concurrent_reviews"]:
        fail(ERR_EVALUATOR_CAPACITY_EXCEEDED,
             "The evaluator is at their concurrent-review cap.")

    row = db.make_row({
        "evaluator_id": evaluator["id"],
        "application_id": application["id"],
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "status": "ASSIGNED",
        "closed_at": None,
    })
    db.assignments[row["id"]] = row

    calculations.refresh_open_assignment_count(evaluator)
    db.touch(evaluator)
    return response.object_response(serializers.review_assignment(row), 201)


@bp.get("/licensure/review-assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate(ALL_ROLES)
    row = lookups.assignment(assignment_id)
    return response.object_response(serializers.review_assignment(row))


@bp.get("/licensure/review-assignments")
def list_assignments():
    authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    evaluator_id = response.query_string("evaluator_id")
    application_id = response.query_string("application_id")
    status = response.query_enum("status", ASSIGNMENT_STATUSES)
    rows = []
    for row in db.assignments.values():
        if evaluator_id is not None and row["evaluator_id"] != evaluator_id:
            continue
        if application_id is not None and row["application_id"] != application_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.review_assignment)
