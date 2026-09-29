"""Applications, the paper-review trail and the screening decision."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import acting_faculty, acting_id, endpoint, require_faculty_program, require_owns_applicant
from envelope import object_response
from errors import ApiError
from store import MIN_REVIEWS_TO_SCREEN, find, insert, must_find, new_row, rows, touch
from validators import body, fk, opt_str, q_enum, q_str, req_enum, req_int, req_str
from routes.common import keep, listing

bp = Blueprint("applications", __name__)

SCREENING_STATUSES = ("RECEIVED", "UNDER_REVIEW", "ADVANCED", "REJECTED", "WITHDRAWN")
INTERVIEW_STATUSES = (
    "NOT_INVITED",
    "INVITED",
    "SCHEDULED",
    "COMPLETED",
    "NO_SHOW",
    "CANCELLED",
)


@bp.post("/applications")
@endpoint("ProgramCoordinator", "NrmpAdmin")
def create_application():
    data = body()
    program = fk(data, "program_id", "programs")
    applicant = fk(data, "applicant_id", "applicants")
    if program is None or applicant is None:
        # The referenced rows resolved above; anything left is a shape problem.
        req_str(data, "program_id")
        req_str(data, "applicant_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    for existing in calc.program_applications(program["id"]):
        if existing["applicant_id"] == applicant["id"]:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                "This applicant already has an application to this program.",
            )

    row = new_row(
        program_id=program["id"],
        applicant_id=applicant["id"],
        screening_status="RECEIVED",
        interview_status="NOT_INVITED",
        provisional_screen_score=0.0,
        final_screen_score=None,
        committee_score=None,
        withdrawn_reason=None,
    )
    insert("applications", row)
    return object_response(serializers.application(row), 201)


@bp.get("/applications")
@endpoint(
    "ProgramCoordinator",
    "ProgramDirector",
    "Reviewer",
    "Interviewer",
    "CommitteeMember",
    "ComplianceOfficer",
    "NrmpAdmin",
)
def list_applications():
    items = rows("applications")
    items = keep(items, "program_id", q_str("program_id"))
    items = keep(items, "applicant_id", q_str("applicant_id"))
    items = keep(items, "screening_status", q_enum("screening_status", SCREENING_STATUSES))
    items = keep(items, "interview_status", q_enum("interview_status", INTERVIEW_STATUSES))
    return listing(items, serializers.application)


@bp.get("/applications/<application_id>")
@endpoint(
    "ProgramCoordinator",
    "ProgramDirector",
    "Reviewer",
    "Interviewer",
    "CommitteeMember",
    "ComplianceOfficer",
    "NrmpAdmin",
    "Applicant",
)
def read_application(application_id):
    return object_response(serializers.application(must_find("applications", application_id)))


# ------------------------------------------------------------------ reviews
@bp.post("/applications/<application_id>/reviews")
@endpoint("Reviewer")
def create_review(application_id):
    application = must_find("applications", application_id)
    data = body()
    academic = req_int(data, "academic_points", minimum=0, maximum=40)
    experience = req_int(data, "experience_points", minimum=0, maximum=30)
    holistic = req_int(data, "holistic_points", minimum=0, maximum=30)

    program = helpers.program_of_application(application)
    helpers.require_phase(program, ("REVIEW_OPEN",))
    helpers.require_state(application, "screening_status", ("RECEIVED", "UNDER_REVIEW"))

    faculty = acting_faculty()
    if faculty is not None and application["applicant_id"] in (
        faculty.get("conflict_applicant_ids") or []
    ):
        raise ApiError("ERR_CONFLICT_OF_INTEREST")

    require_faculty_program(faculty, application["program_id"])

    for existing in calc.application_reviews(application_id):
        if existing["reviewer_id"] == acting_id():
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", "This reviewer already reviewed the application."
            )

    review = new_row(
        application_id=application_id,
        reviewer_id=acting_id(),
        academic_points=academic,
        experience_points=experience,
        holistic_points=holistic,
        status="SUBMITTED",
    )
    insert("application_reviews", review)

    if application["screening_status"] == "RECEIVED":
        application["screening_status"] = "UNDER_REVIEW"
    helpers.refresh_provisional(application)
    touch(application)

    return object_response(serializers.application_review(review), 201)


@bp.get("/application-reviews")
@endpoint("ProgramCoordinator", "ProgramDirector", "Reviewer", "ComplianceOfficer", "NrmpAdmin")
def list_reviews():
    items = rows("application_reviews")
    items = keep(items, "application_id", q_str("application_id"))
    items = keep(items, "reviewer_id", q_str("reviewer_id"))
    return listing(items, serializers.application_review)


@bp.get("/application-reviews/<review_id>")
@endpoint("ProgramCoordinator", "ProgramDirector", "Reviewer", "ComplianceOfficer", "NrmpAdmin")
def read_review(review_id):
    return object_response(
        serializers.application_review(must_find("application_reviews", review_id))
    )


# ------------------------------------------------------------------ screening
@bp.post("/applications/<application_id>/screen")
@endpoint("ProgramCoordinator")
def screen_application(application_id):
    application = must_find("applications", application_id)
    data = body()
    decision = req_enum(data, "decision", ("ADVANCE", "REJECT"))

    program = helpers.program_of_application(application)
    helpers.require_phase(program, ("REVIEW_OPEN",))
    helpers.require_state(application, "screening_status", ("UNDER_REVIEW",))

    applicant = helpers.applicant_of_application(application)

    if decision == "ADVANCE":
        if applicant is None:
            raise ApiError("ERR_SCREENING_FILTER_FAILED")
        if applicant["step2_score"] < program["min_step2_score"]:
            raise ApiError(
                "ERR_SCREENING_FILTER_FAILED", "Step 2 CK score is below the program floor."
            )
        if applicant["medical_school_type"] == "IMG" and not program["img_accepted"]:
            raise ApiError(
                "ERR_SCREENING_FILTER_FAILED", "The program does not accept IMG applicants."
            )
        if applicant["visa_status"] in ("NEEDS_J1", "NEEDS_H1B") and not program[
            "visa_sponsorship_allowed"
        ]:
            raise ApiError(
                "ERR_SCREENING_FILTER_FAILED", "The program does not sponsor work authorization."
            )

    if calc.review_count(application) < MIN_REVIEWS_TO_SCREEN:
        raise ApiError(
            "ERR_INSUFFICIENT_EVALUATIONS",
            "At least %d reviews are required before a screening decision."
            % MIN_REVIEWS_TO_SCREEN,
        )

    application["screening_status"] = "ADVANCED" if decision == "ADVANCE" else "REJECTED"
    if applicant is not None:
        helpers.write_final_screen_score(application, applicant)
    touch(application)
    return object_response(serializers.application(application))


# ------------------------------------------------------------------ withdraw
@bp.post("/applications/<application_id>/withdraw")
@endpoint("Applicant")
def withdraw_application(application_id):
    application = must_find("applications", application_id)
    data = body()
    reason = opt_str(data, "withdrawn_reason", max_len=2000)

    helpers.require_state(
        application, "screening_status", ("RECEIVED", "UNDER_REVIEW", "ADVANCED")
    )
    require_owns_applicant(application["applicant_id"])

    application["screening_status"] = "WITHDRAWN"
    application["withdrawn_reason"] = reason
    helpers.withdraw_application_cascade(application)
    touch(application)
    return object_response(serializers.application(application))
