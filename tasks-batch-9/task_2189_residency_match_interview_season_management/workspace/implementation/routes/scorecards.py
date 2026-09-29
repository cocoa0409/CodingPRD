"""Interview rubric score cards and the committee roll-up."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import (
    acting_faculty,
    acting_id,
    endpoint,
    require_faculty_program,
    require_program_director,
)
from envelope import object_response
from errors import ApiError
from store import find, insert, must_find, new_row, rows, touch
from validators import body, fk, q_enum, q_str, req_int, req_str
from routes.common import keep, listing

bp = Blueprint("scorecards", __name__)

CARD_STATUSES = ("DRAFT", "SUBMITTED", "AMEND_REQUESTED", "LOCKED")
DOMAINS = (
    "communication_score",
    "clinical_reasoning_score",
    "professionalism_score",
    "teamwork_score",
)


def _read_domains(data):
    return {field: req_int(data, field, minimum=1, maximum=10) for field in DOMAINS}


@bp.post("/score-cards")
@endpoint("Interviewer")
def create_score_card():
    data = body()
    assignment = fk(data, "assignment_id", "interview_assignments")
    application = fk(data, "application_id", "applications")
    if assignment is None or application is None:
        req_str(data, "assignment_id")
        req_str(data, "application_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    domains = _read_domains(data)

    # priority 8 - the acting interviewer owns the panel seat
    if assignment["faculty_member_id"] != acting_id():
        raise ApiError("ERR_OWNERSHIP_MISMATCH")

    # priority 8 - the scored application is booked into that panel seat's slot
    booked = False
    for invitation in calc.slot_invitations(assignment["slot_id"]):
        if (
            invitation["status"] == "ACCEPTED"
            and invitation["application_id"] == application["id"]
        ):
            booked = True
            break
    if not booked:
        raise ApiError(
            "ERR_CROSS_REFERENCE_MISMATCH",
            "The application is not booked into the assignment's slot.",
        )

    # priority 10 - one card per (assignment, application)
    for other in rows("score_cards"):
        if (
            other["assignment_id"] == assignment["id"]
            and other["application_id"] == application["id"]
        ):
            raise ApiError("ERR_DUPLICATE_RESOURCE", "A card already exists for this pairing.")

    row = new_row(
        assignment_id=assignment["id"],
        application_id=application["id"],
        domain_average=None,
        status="DRAFT",
        **domains
    )
    insert("score_cards", row)
    return object_response(serializers.score_card(row), 201)


@bp.get("/score-cards")
@endpoint("ProgramCoordinator", "ProgramDirector", "Interviewer", "CommitteeMember", "NrmpAdmin")
def list_score_cards():
    items = rows("score_cards")
    items = keep(items, "assignment_id", q_str("assignment_id"))
    items = keep(items, "application_id", q_str("application_id"))
    items = keep(items, "status", q_enum("status", CARD_STATUSES))
    return listing(items, serializers.score_card)


@bp.get("/score-cards/<card_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "Interviewer", "CommitteeMember", "NrmpAdmin")
def read_score_card(card_id):
    return object_response(serializers.score_card(must_find("score_cards", card_id)))


@bp.post("/score-cards/<card_id>/submit")
@endpoint("Interviewer")
def submit_score_card(card_id):
    card = must_find("score_cards", card_id)
    assignment = find("interview_assignments", card["assignment_id"])
    application = find("applications", card["application_id"])

    helpers.require_state(card, "status", ("DRAFT",))
    if assignment is None or assignment["status"] != "ASSIGNED":
        helpers.invalid_state("The authoring panel seat is no longer ASSIGNED.")
    if application is None or application["interview_status"] != "COMPLETED":
        helpers.invalid_state("The interview has not been completed.")

    if assignment["faculty_member_id"] != acting_id():
        raise ApiError("ERR_OWNERSHIP_MISMATCH")

    card["status"] = "SUBMITTED"
    card["domain_average"] = float(calc.card_domain_average(card))
    touch(card)
    helpers.refresh_committee_score(application)
    return object_response(serializers.score_card(card))


@bp.post("/score-cards/<card_id>/request-amendment")
@endpoint("ProgramDirector")
def request_amendment(card_id):
    card = must_find("score_cards", card_id)
    application = find("applications", card["application_id"])

    helpers.require_state(card, "status", ("SUBMITTED",))
    if application is not None and helpers.program_has_certified_list(application["program_id"]):
        helpers.invalid_state("The program's rank list is already certified.")

    faculty = acting_faculty()
    require_program_director(faculty)
    if application is not None:
        require_faculty_program(faculty, application["program_id"])

    card["status"] = "AMEND_REQUESTED"
    touch(card)
    return object_response(serializers.score_card(card))


@bp.post("/score-cards/<card_id>/revise")
@endpoint("Interviewer")
def revise_score_card(card_id):
    card = must_find("score_cards", card_id)
    data = body()
    domains = _read_domains(data)

    helpers.require_state(card, "status", ("AMEND_REQUESTED",))

    assignment = find("interview_assignments", card["assignment_id"])
    if assignment is None or assignment["faculty_member_id"] != acting_id():
        raise ApiError("ERR_OWNERSHIP_MISMATCH")

    card.update(domains)
    card["status"] = "DRAFT"
    card["domain_average"] = None
    touch(card)

    application = find("applications", card["application_id"])
    if application is not None:
        helpers.refresh_committee_score(application)
    return object_response(serializers.score_card(card))
