"""The analyst's format decision and its arithmetic (PRD section 3.5)."""

import lookup
import serializers
import validate
from db import db, write
from errors import fail
from flask import Blueprint
from logical_clock import clock
from middleware import endpoint
from response import object_response
from routes import common
from routes.common import ALL_ROLES, PREFIX
from services import calc, counters
from services.clearance import recompute_for_thesis
from timeutil import business_days_between

bp = Blueprint("reviews", __name__, url_prefix=PREFIX)

DECISIONS = ("ACCEPT", "RETURN_REVISIONS")


@bp.get("/format-reviews/<review_id>")
@endpoint(ALL_ROLES)
def read_review(user_id, role, review_id):
    return object_response(
        serializers.format_review(lookup.get_format_review(review_id))
    )


@bp.post("/format-reviews/<review_id>/decision")
@endpoint(["GradSchoolAnalyst"])
def decide_review(user_id, role, review_id):
    review = lookup.get_format_review(review_id)
    body = validate.get_body()
    decision = validate.req_enum(body, "decision", DECISIONS)
    critical = validate.req_int(body, "critical_defect_count", minimum=0)
    major = validate.req_int(body, "major_defect_count", minimum=0)
    minor = validate.req_int(body, "minor_defect_count", minimum=0)
    validate.opt_str(body, "review_note")

    thesis = db.theses.get(review["thesis_id"])
    if thesis is not None:
        common.require_term_open(thesis)

    if review["status"] != "PENDING_REVIEW":
        fail(
            "ERR_FORMAT_REVIEW_STATE_INVALID",
            "Only a PENDING_REVIEW cycle may be decided",
        )

    page_count = thesis["page_count"] if thesis is not None else 0
    score = calc.severity_weighted_defect_score(page_count, critical, major, minor)

    if decision == "ACCEPT" and thesis is not None:
        # Stage 12 precedes stage 16.
        if thesis["integrity_state"] == "NOT_SCREENED":
            fail(
                "ERR_SCREENING_REQUIRED",
                "The document has not been screened for similarity",
            )
        if thesis["integrity_state"] in common.INTEGRITY_HOLD_STATES:
            fail(
                "ERR_INTEGRITY_HOLD_ACTIVE",
                "An integrity hold is active on the document",
            )
        if score >= calc.REVISION_MANDATORY_THRESHOLD:
            fail(
                "ERR_DEFECT_SCORE_REQUIRES_REVISIONS",
                "A severity-weighted defect score of %s mandates revisions" % score,
            )
        if not common.permissions_complete(thesis):
            fail(
                "ERR_PERMISSIONS_INCOMPLETE",
                "The third-party permission dossier is not complete",
            )

    decided_at = clock.now()
    turnaround = business_days_between(review["opened_at"], decided_at)

    if decision == "ACCEPT":
        write(
            review,
            status="ACCEPTED",
            decision="ACCEPT",
            decided_at=decided_at,
            decided_by_user_id=user_id,
            critical_defect_count=critical,
            major_defect_count=major,
            minor_defect_count=minor,
            severity_weighted_defect_score=score,
            revision_due_at=None,
            turnaround_bdays=turnaround,
        )
        if thesis is not None:
            values = counters.thesis_counter_values(thesis)
            write(
                thesis,
                workflow_state="FORMAT_ACCEPTED",
                accepted_at=decided_at,
                analyst_turnaround_bdays_total=values["analyst_turnaround_bdays_total"],
            )
    else:
        term = common.term_of(thesis) if thesis is not None else None
        due = None
        if term is not None:
            due = calc.format_revision_window(
                review["cycle_number"], decided_at, page_count, term
            )
        write(
            review,
            status="REVISIONS_REQUIRED",
            decision="RETURN_REVISIONS",
            decided_at=decided_at,
            decided_by_user_id=user_id,
            critical_defect_count=critical,
            major_defect_count=major,
            minor_defect_count=minor,
            severity_weighted_defect_score=score,
            revision_due_at=due,
            turnaround_bdays=turnaround,
        )
        if thesis is not None:
            values = counters.thesis_counter_values(thesis)
            write(
                thesis,
                workflow_state="FORMAT_REVISIONS_REQUIRED",
                analyst_turnaround_bdays_total=values["analyst_turnaround_bdays_total"],
            )

    if thesis is not None:
        recompute_for_thesis(thesis)
    return object_response(serializers.format_review(review))
