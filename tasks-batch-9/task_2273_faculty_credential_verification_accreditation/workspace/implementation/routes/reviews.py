"""Accreditor reviews, findings and the remediation negotiation (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import clock
import db
import guards
import middleware
import response
import serialize
import util
import validate
from constants import (
    ACCREDITATION_LIAISON, ACCREDITOR_REVIEWER, CLOSED_REVIEW_STATUSES, READ_ROLES,
    REVIEW_STATUSES, REVIEW_TYPES, RISK_TIERS,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import calc, domain, lookup

bp = Blueprint("reviews", __name__)


def _write_risk(review, program, anchor):
    risk = calc.review_risk(program, anchor)
    review["preliminary_risk_index"] = risk["preliminary_risk_index"]
    review["risk_tier"] = risk["risk_tier"]
    review["risk_index"] = risk["risk_index"]
    review["response_due_date"] = util.date_to_str(risk["response_due_date"])
    return risk


@bp.route("/accreditor-reviews", methods=["POST"])
def schedule_review():
    middleware.require_role(ACCREDITOR_REVIEWER)
    payload = validate.body()

    program_id = validate.req_str(payload, "program_id")
    review_type = validate.req_enum(payload, "review_type", REVIEW_TYPES)
    window_start = validate.req_date(payload, "window_start_date")
    window_end = validate.req_date(payload, "window_end_date")

    lookup.program(program_id)

    for other in lookup.reviews_of_program(program_id):
        if other["status"] in CLOSED_REVIEW_STATUSES:
            continue
        other_start = util.parse_date(other["window_start_date"])
        other_end = util.parse_date(other["window_end_date"])
        if other_start is None or other_end is None:
            continue
        if window_start <= other_end and other_start <= window_end:
            raise ApiError("ERR_REVIEW_WINDOW_OVERLAP")

    if window_start > window_end:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_start_date must be at or before window_end_date.")

    row = db.new_row(
        program_id=program_id,
        review_type=review_type,
        window_start_date=util.date_to_str(window_start),
        window_end_date=util.date_to_str(window_end),
        status="SCHEDULED",
        finding_count=0,
        unqualified_assignment_ids=[],
        preliminary_risk_index=Decimal("0.00"),
        risk_tier="LOW",
        risk_index=Decimal("0.00"),
        response_due_date=None,
        response_round=0,
        response_narrative=None,
    )
    store.reviews[row["id"]] = row
    return response.created(serialize.review(row))


@bp.route("/accreditor-reviews/<review_id>", methods=["GET"])
def read_review(review_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.review(lookup.review(review_id)))


@bp.route("/accreditor-reviews", methods=["GET"])
def list_reviews():
    middleware.require_role(*READ_ROLES)
    program_id = validate.q_str("program_id")
    status = validate.q_enum("status", REVIEW_STATUSES)
    review_type = validate.q_enum("review_type", REVIEW_TYPES)
    risk_tier = validate.q_enum("risk_tier", RISK_TIERS)
    rows = [r for r in db.ordered(store.reviews)
            if match(r, "program_id", program_id)
            and match(r, "status", status)
            and match(r, "review_type", review_type)
            and match(r, "risk_tier", risk_tier)]
    return list_response(rows, serialize.review)


@bp.route("/accreditor-reviews/<review_id>/status", methods=["POST"])
def review_status(review_id):
    middleware.require_role(ACCREDITOR_REVIEWER)
    payload = validate.body()
    to_status = validate.req_enum(payload, "to_status", REVIEW_STATUSES)
    validate.opt_str(payload, "note")

    review = lookup.review(review_id)
    current = review["status"]
    program = store.programs.get(review["program_id"])

    allowed = {
        ("SCHEDULED", "IN_PROGRESS"),
        ("FINDINGS_ISSUED", "CLOSED_ACCEPTED"),
        ("RESPONSE_SUBMITTED", "CLOSED_ACCEPTED"),
        ("RESPONSE_SUBMITTED", "REMEDIATION_REQUIRED"),
        ("RESPONSE_SUBMITTED", "CLOSED_SANCTION"),
    }
    if (current, to_status) not in allowed:
        guards.invalid_state("A review in %s may not move to %s." % (current, to_status))

    if to_status == "CLOSED_SANCTION" and int(review.get("response_round", 0)) < 2:
        guards.invalid_state("A sanction requires at least two response rounds.")

    if to_status == "IN_PROGRESS":
        window_start = util.parse_date(review["window_start_date"])
        if window_start is None or clock.current_date() < window_start:
            raise ApiError("ERR_INVALID_WINDOW",
                           "A review may not start before its window_start_date.")

    if to_status == "CLOSED_ACCEPTED":
        if program is None:
            raise ApiError("ERR_PROGRAM_ADEQUACY_INSUFFICIENT")
        guards.require_program_clean(program)

    review["status"] = to_status

    if to_status == "REMEDIATION_REQUIRED":
        anchor = lookup.anchor_roster_for_program(review["program_id"])
        _write_risk(review, program or {"min_terminal_ratio": 0, "id": None}, anchor)

    touch(review)
    return response.ok(serialize.review(review))


@bp.route("/accreditor-reviews/<review_id>/findings", methods=["POST"])
def issue_findings(review_id):
    middleware.require_role(ACCREDITOR_REVIEWER)
    payload = validate.body()
    finding_count = validate.req_int(payload, "finding_count", minimum=0)
    validate.opt_str(payload, "narrative")

    review = lookup.review(review_id)
    program = store.programs.get(review["program_id"])

    anchor = lookup.anchor_roster_for_program(review["program_id"])
    if anchor is None:
        raise ApiError("ERR_ROSTER_NOT_FOUND")

    if review["status"] != "IN_PROGRESS":
        guards.invalid_state("A review in %s may not issue findings." % review["status"])

    included = lookup.included_assignments(review["program_id"], anchor["term_id"])
    listed = [a for a in included
              if a["status"] in ("PENDING_VERIFICATION", "EXCEPTION_FLAGGED",
                                 "REMEDIATION_IN_PROGRESS")]

    review["finding_count"] = finding_count
    review["unqualified_assignment_ids"] = [a["id"] for a in listed]
    _write_risk(review, program, anchor)

    if finding_count > 0:
        review["status"] = "REMEDIATION_REQUIRED"
    else:
        review["status"] = "FINDINGS_ISSUED"
    touch(review)

    if finding_count > 0:
        moved = False
        for assignment in listed:
            if assignment["status"] != "EXCEPTION_FLAGGED":
                continue
            assignment["status"] = "REMEDIATION_IN_PROGRESS"
            assignment["remediation_action"] = "REASSIGN_PENDING"
            touch(assignment)
            moved = True
        if moved:
            domain.recompute_roster(anchor)
            if program is not None:
                domain.write_program_adequacy(program, anchor["term_id"])

    return response.ok(serialize.review(review))


@bp.route("/accreditor-reviews/<review_id>/response", methods=["POST"])
def file_response(review_id):
    middleware.require_role(ACCREDITATION_LIAISON)
    payload = validate.body()
    narrative = validate.req_str(payload, "response_narrative")

    review = lookup.review(review_id)

    if review["status"] != "REMEDIATION_REQUIRED":
        guards.invalid_state("A review in %s takes no remediation response."
                             % review["status"])

    due = util.parse_date(review.get("response_due_date"))
    if due is not None and clock.current_date() > due:
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED")

    review["status"] = "RESPONSE_SUBMITTED"
    review["response_narrative"] = narrative
    review["response_round"] = int(review.get("response_round", 0)) + 1
    touch(review)
    return response.ok(serialize.review(review))
