"""The document record, its reverse-reachability reads and the format cycle."""

import lookup
import serializers
import validate
from db import by_created_at, db, new_row, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import array_response, object_response
from routes import common
from routes.common import ALL_ROLES, PREFIX
from services import calc, counters
from services.clearance import (
    ensure_clearance,
    evaluate,
    recompute_for_thesis,
    variant_for_term,
)

bp = Blueprint("theses", __name__, url_prefix=PREFIX)

DOCUMENT_TYPES = ("THESIS", "DISSERTATION")

WORKFLOW_STATES = (
    "DRAFT",
    "COMMITTEE_PENDING",
    "COMMITTEE_APPROVED",
    "DEFENSE_SCHEDULED",
    "DEFENSE_ANNOUNCED",
    "DEFENSE_PASSED",
    "DEFENSE_PASSED_WITH_REVISIONS",
    "DEFENSE_FAILED",
    "UNDER_FORMAT_REVIEW",
    "FORMAT_REVISIONS_REQUIRED",
    "FORMAT_ACCEPTED",
    "DEPOSITED",
    "CONFERRED",
    "TERMINATED",
)

LIVE_THESIS_EXCLUSIONS = ("DEFENSE_FAILED", "TERMINATED", "CONFERRED")

FORMAT_SUBMISSION_STATES = (
    "DEFENSE_PASSED",
    "DEFENSE_PASSED_WITH_REVISIONS",
    "FORMAT_REVISIONS_REQUIRED",
)


# --------------------------------------------------------------------- reads


@bp.get("/theses")
@endpoint(ALL_ROLES)
def list_theses(user_id, role):
    limit, offset = validate.pagination()
    student_id = validate.query_str("student_id")
    term_id = validate.query_str("term_id")
    workflow_state = validate.query_enum("workflow_state", WORKFLOW_STATES)

    rows = list(db.theses.values())
    if student_id is not None:
        rows = [r for r in rows if r["student_id"] == student_id]
    if term_id is not None:
        rows = [r for r in rows if r["term_id"] == term_id]
    if workflow_state is not None:
        rows = [r for r in rows if r["workflow_state"] == workflow_state]

    rows = by_created_at(rows)
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.thesis(row) for row in page], limit, offset, total
    )


@bp.get("/theses/<thesis_id>")
@endpoint(ALL_ROLES)
def read_thesis(user_id, role, thesis_id):
    return object_response(serializers.thesis(lookup.get_thesis(thesis_id)))


@bp.get("/theses/<thesis_id>/committee")
@endpoint(ALL_ROLES)
def read_thesis_committee(user_id, role, thesis_id):
    limit, offset = validate.pagination()
    thesis = lookup.get_thesis(thesis_id)
    committee = lookup.committee_of_thesis(thesis["id"])
    rows = [committee] if committee is not None else []
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.committee(row) for row in page], limit, offset, total
    )


@bp.get("/theses/<thesis_id>/format-reviews")
@endpoint(ALL_ROLES)
def read_thesis_format_reviews(user_id, role, thesis_id):
    limit, offset = validate.pagination()
    thesis = lookup.get_thesis(thesis_id)
    rows = sorted(
        lookup.reviews_of_thesis(thesis["id"]),
        key=lambda r: (r["cycle_number"], r["created_at"], r["_seq"]),
    )
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.format_review(row) for row in page], limit, offset, total
    )


@bp.get("/theses/<thesis_id>/embargo-requests")
@endpoint(ALL_ROLES)
def read_thesis_embargo_requests(user_id, role, thesis_id):
    limit, offset = validate.pagination()
    thesis = lookup.get_thesis(thesis_id)
    rows = by_created_at(lookup.embargoes_of_thesis(thesis["id"]))
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.embargo_request(row) for row in page], limit, offset, total
    )


@bp.get("/theses/<thesis_id>/permission-records")
@endpoint(ALL_ROLES)
def read_thesis_permission_records(user_id, role, thesis_id):
    limit, offset = validate.pagination()
    thesis = lookup.get_thesis(thesis_id)
    rows = by_created_at(lookup.permissions_of_thesis(thesis["id"]))
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.permission_record(row) for row in page], limit, offset, total
    )


@bp.get("/theses/<thesis_id>/integrity-screenings")
@endpoint(ALL_ROLES)
def read_thesis_screenings(user_id, role, thesis_id):
    limit, offset = validate.pagination()
    thesis = lookup.get_thesis(thesis_id)
    rows = by_created_at(lookup.screenings_of_thesis(thesis["id"]))
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.integrity_screening(row) for row in page], limit, offset, total
    )


@bp.get("/theses/<thesis_id>/repository-deposit")
@endpoint(ALL_ROLES)
def read_thesis_deposit(user_id, role, thesis_id):
    limit, offset = validate.pagination()
    thesis = lookup.get_thesis(thesis_id)
    rows = by_created_at(lookup.deposits_of_thesis(thesis["id"]))
    page, total = validate.paginate(rows, limit, offset)
    return array_response(
        [serializers.repository_deposit(row) for row in page], limit, offset, total
    )


@bp.get("/theses/<thesis_id>/deposit-readiness")
@endpoint(ALL_ROLES)
def deposit_readiness(user_id, role, thesis_id):
    thesis = lookup.get_thesis(thesis_id)
    term = common.term_of(thesis)
    variant = variant_for_term(term)
    outstanding = evaluate(thesis, variant)

    projected_fee = 0
    if term is not None:
        projected_fee = calc.deposit_late_fee_cents(thesis, term, clock.now())

    blocking = None
    if term is not None and term["status"] != "OPEN":
        blocking = "ERR_TERM_DEPOSIT_CLOSED"
    elif thesis["workflow_state"] != "FORMAT_ACCEPTED":
        blocking = "ERR_THESIS_STATE_INVALID"
    elif thesis["integrity_state"] == "NOT_SCREENED":
        blocking = "ERR_SCREENING_REQUIRED"
    elif thesis["integrity_state"] in common.INTEGRITY_HOLD_STATES:
        blocking = "ERR_INTEGRITY_HOLD_ACTIVE"
    elif not common.permissions_complete(thesis):
        blocking = "ERR_PERMISSIONS_INCOMPLETE"
    elif common.embargo_undecided(thesis):
        blocking = "ERR_EMBARGO_UNDECIDED"
    elif any(
        row["status"] == "DEPOSITED" for row in lookup.deposits_of_thesis(thesis["id"])
    ):
        blocking = "ERR_DEPOSIT_ALREADY_EXISTS"

    return object_response(
        {
            "thesis_id": thesis["id"],
            "workflow_state": thesis["workflow_state"],
            "projection_variant": variant,
            "outstanding_items": outstanding,
            "projected_late_fee_cents": projected_fee,
            "next_blocking_error_id": blocking,
        }
    )


# -------------------------------------------------------------------- writes


@bp.post("/theses")
@endpoint(["Student"])
def create_thesis(user_id, role):
    body = validate.get_body()
    student_id = validate.req_str(body, "student_id")
    term_id = validate.req_str(body, "term_id")
    title = validate.req_str(body, "title")
    document_type = validate.req_enum(body, "document_type", DOCUMENT_TYPES)
    page_count = validate.req_int(body, "page_count", minimum=1)
    third_party_item_count = validate.opt_int(
        body, "third_party_item_count", default=0, minimum=0
    )

    student = lookup.get_student(student_id)
    term = lookup.get_term(term_id)

    if role == "Student" and student["id"] != user_id:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "A candidate may only open their own document record",
        )

    for existing in lookup.theses_of_student(student["id"]):
        if existing["term_id"] != term["id"]:
            continue
        if existing["workflow_state"] not in LIVE_THESIS_EXCLUSIONS:
            fail(
                "ERR_DUPLICATE_THESIS_FOR_TERM",
                "The candidate already holds a live document in this term",
            )

    row = new_row(
        student_id=student["id"],
        term_id=term["id"],
        title=title,
        document_type=document_type,
        page_count=page_count,
        third_party_item_count=third_party_item_count,
        workflow_state="DRAFT",
        integrity_state="NOT_SCREENED",
        format_cycle_count=0,
        documented_permission_count=0,
        analyst_turnaround_bdays_total=0,
        accepted_at=None,
    )
    db.theses[row["id"]] = row
    ensure_clearance(student["id"])
    return object_response(serializers.thesis(row), 201)


@bp.post("/theses/<thesis_id>/format-submissions")
@endpoint(["Student"])
def create_format_submission(user_id, role, thesis_id):
    thesis = lookup.get_thesis(thesis_id)
    common.require_owner(role, user_id, thesis)
    common.require_term_open(thesis)

    if thesis["workflow_state"] not in FORMAT_SUBMISSION_STATES:
        fail(
            "ERR_THESIS_STATE_INVALID",
            "A format review cycle cannot be opened from workflow_state '%s'"
            % thesis["workflow_state"],
        )

    pending_revisions = [
        row
        for row in lookup.reviews_of_thesis(thesis["id"])
        if row["status"] == "REVISIONS_REQUIRED"
    ]
    if thesis["workflow_state"] == "FORMAT_REVISIONS_REQUIRED":
        for review in pending_revisions:
            due = review["revision_due_at"]
            if due is not None and clock.now() > due:
                fail(
                    "ERR_REVISION_WINDOW_EXPIRED",
                    "The revision window closed at %s" % due,
                )

    row = new_row(
        thesis_id=thesis["id"],
        cycle_number=thesis["format_cycle_count"] + 1,
        opened_at=clock.now(),
        decided_at=None,
        decided_by_user_id=None,
        decision=None,
        critical_defect_count=0,
        major_defect_count=0,
        minor_defect_count=0,
        severity_weighted_defect_score=calc.round_half_up(0, 2),
        revision_due_at=None,
        turnaround_bdays=None,
        status="PENDING_REVIEW",
    )
    db.format_reviews[row["id"]] = row

    for review in pending_revisions:
        write(review, status="SUPERSEDED")

    values = counters.thesis_counter_values(thesis)
    write(
        thesis,
        workflow_state="UNDER_FORMAT_REVIEW",
        format_cycle_count=values["format_cycle_count"],
        analyst_turnaround_bdays_total=values["analyst_turnaround_bdays_total"],
    )
    recompute_for_thesis(thesis)

    return object_response(serializers.format_review(row), 201)
