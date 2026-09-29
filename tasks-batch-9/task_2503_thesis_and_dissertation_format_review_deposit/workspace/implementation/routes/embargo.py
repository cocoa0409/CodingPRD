"""Embargo requests, duration caps and the dean's ruling (PRD section 3.7)."""

import lookup
import serializers
import validate
from db import db, new_row, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import object_response
from routes import common
from routes.common import ALL_ROLES, PREFIX
from services import calc
from services.clearance import recompute_for_thesis

bp = Blueprint("embargo", __name__, url_prefix=PREFIX)

REASON_CODES = ("PATENT_PENDING", "PUBLISHER_AGREEMENT", "SENSITIVE_DATA", "HUMAN_SUBJECTS")

DECISIONS = ("APPROVE", "PARTIALLY_APPROVE", "DENY", "REQUEST_INFO")

ALLOWED_THESIS_STATES = (
    "DEFENSE_PASSED",
    "DEFENSE_PASSED_WITH_REVISIONS",
    "UNDER_FORMAT_REVIEW",
    "FORMAT_REVISIONS_REQUIRED",
    "FORMAT_ACCEPTED",
)

UNDECIDED_STATUSES = ("REQUESTED", "MORE_INFO_REQUIRED")


@bp.get("/embargo-requests/<request_id>")
@endpoint(ALL_ROLES)
def read_request(user_id, role, request_id):
    return object_response(
        serializers.embargo_request(lookup.get_embargo_request(request_id))
    )


@bp.post("/embargo-requests")
@endpoint(["Student"])
def create_request(user_id, role):
    body = validate.get_body()
    thesis_id = validate.req_str(body, "thesis_id")
    reason_code = validate.req_enum(body, "reason_code", REASON_CODES)
    requested_months = validate.req_int(body, "requested_months", minimum=1)
    justification = validate.req_str(body, "justification")
    expected_version = validate.req_int(body, "expected_thesis_version", minimum=1)

    thesis = lookup.get_thesis(thesis_id)
    common.require_owner(role, user_id, thesis)
    common.require_thesis_version(thesis, expected_version)
    common.require_term_open(thesis)

    if thesis["workflow_state"] not in ALLOWED_THESIS_STATES:
        fail(
            "ERR_THESIS_STATE_INVALID",
            "An embargo cannot be requested while the document is '%s'"
            % thesis["workflow_state"],
        )

    student = db.students.get(thesis["student_id"])
    degree_level = student["degree_level"] if student is not None else "DOCTORAL"
    cap = calc.embargo_cap(reason_code, degree_level)
    if requested_months > cap:
        fail(
            "ERR_EMBARGO_DURATION_EXCEEDS_CAP",
            "A %s embargo for a %s candidate is capped at %d months"
            % (reason_code, degree_level, cap),
        )

    row = new_row(
        thesis_id=thesis["id"],
        reason_code=reason_code,
        requested_months=requested_months,
        justification=justification,
        approved_months=None,
        status="REQUESTED",
        info_request_count=0,
        decided_by_user_id=None,
        decided_at=None,
        release_date=None,
        release_anchor=None,
        decision_note=None,
    )

    for existing in lookup.embargoes_of_thesis(thesis["id"]):
        if existing["status"] in UNDECIDED_STATUSES:
            write(existing, status="SUPERSEDED")

    db.embargo_requests[row["id"]] = row

    write(thesis)
    recompute_for_thesis(thesis)

    return object_response(serializers.embargo_request(row), 201)


@bp.post("/embargo-requests/<request_id>/decision")
@endpoint(["GraduateDean"])
def decide_request(user_id, role, request_id):
    embargo = lookup.get_embargo_request(request_id)
    body = validate.get_body()
    decision = validate.req_enum(body, "decision", DECISIONS)
    approved_months = validate.opt_int(body, "approved_months")
    decision_note = validate.opt_str(body, "decision_note")

    thesis = db.theses.get(embargo["thesis_id"])
    if thesis is not None:
        common.require_term_open(thesis)

    if embargo["status"] != "REQUESTED":
        fail(
            "ERR_EMBARGO_STATE_INVALID",
            "Only a REQUESTED embargo may be ruled on",
        )

    # Stage 13: the dean who approved the committee may not rule on the embargo.
    committee = (
        lookup.committee_of_thesis(thesis["id"]) if thesis is not None else None
    )
    if (
        committee is not None
        and committee["approved_by_user_id"] is not None
        and committee["approved_by_user_id"] == user_id
    ):
        fail(
            "ERR_DUTY_SEGREGATION_VIOLATION",
            "The dean who approved the committee may not rule on the embargo",
        )

    now = clock.now()
    if decision == "APPROVE":
        write(
            embargo,
            status="APPROVED",
            approved_months=embargo["requested_months"],
            decided_at=now,
            decided_by_user_id=user_id,
            decision_note=decision_note,
        )
    elif decision == "PARTIALLY_APPROVE":
        if (
            approved_months is None
            or approved_months < 1
            or approved_months >= embargo["requested_months"]
        ):
            fail(
                "ERR_EMBARGO_DURATION_EXCEEDS_CAP",
                "A partial approval must be at least 1 month and strictly shorter "
                "than the requested %d months" % embargo["requested_months"],
            )
        write(
            embargo,
            status="PARTIALLY_APPROVED",
            approved_months=approved_months,
            decided_at=now,
            decided_by_user_id=user_id,
            decision_note=decision_note,
        )
    elif decision == "DENY":
        write(
            embargo,
            status="DENIED",
            approved_months=0,
            decided_at=now,
            decided_by_user_id=user_id,
            decision_note=decision_note,
        )
    else:
        write(
            embargo,
            status="MORE_INFO_REQUIRED",
            info_request_count=embargo["info_request_count"] + 1,
            decision_note=decision_note,
        )

    if thesis is not None:
        recompute_for_thesis(thesis)
    return object_response(serializers.embargo_request(embargo))


@bp.post("/embargo-requests/<request_id>/supplement")
@endpoint(["Student"])
def supplement_request(user_id, role, request_id):
    embargo = lookup.get_embargo_request(request_id)
    body = validate.get_body()
    justification = validate.req_str(body, "justification")

    thesis = db.theses.get(embargo["thesis_id"])
    if thesis is not None:
        common.require_owner(role, user_id, thesis)
        common.require_term_open(thesis)

    if embargo["status"] != "MORE_INFO_REQUIRED":
        fail(
            "ERR_EMBARGO_STATE_INVALID",
            "Only a MORE_INFO_REQUIRED embargo may be supplemented",
        )

    write(embargo, status="REQUESTED", justification=justification)
    if thesis is not None:
        recompute_for_thesis(thesis)
    return object_response(serializers.embargo_request(embargo))
