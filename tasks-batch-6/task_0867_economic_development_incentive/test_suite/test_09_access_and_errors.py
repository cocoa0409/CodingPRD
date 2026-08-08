"""Authentication, authorization, not-found and validation errors, and invalid-state guards
on activate/approve."""
from test_helpers import (
    validate_error, ApiErrorId, NONEXISTENT_UUID,
    create_program, create_program_payload, create_application, create_application_payload,
    setup_active_agreement,
    make_applicant_headers, make_director_headers, TEST_USERS,
)

APPLICANT = make_applicant_headers("applicant-1")
DIRECTOR = make_director_headers("director-1")
PUBLIC = TEST_USERS["public_headers"]


def test_program_get_unknown_id_returns_404(api):
    """PRD §2.4: "an unknown program yields `ERR_PROGRAM_NOT_FOUND`".

    Design: Corner/entities/program_get_unknown_id_returns_404
    """
    validate_error(api.get_program(NONEXISTENT_UUID, DIRECTOR), ApiErrorId.ERR_PROGRAM_NOT_FOUND)


def test_application_missing_required_field_returns_422(api):
    """PRD §2.10: "Body well-formedness (priority 4) requires that all required fields are
    present, every enum value is in range, integer amounts are non-negative, a covenant's
    `measurement_end_date` is greater than or equal to its `measurement_start_date`, a report's
    `period_end_date` is strictly greater than its `period_start_date`, and any `term_years` is at
    least 1. Any breach of these yields `ERR_VALIDATION` (HTTP 422)." proposed_jobs is omitted.

    Design: Corner/entities/application_missing_required_field_returns_422
    """
    prog = create_program()
    payload = {
        "program_id": prog["id"],
        "applicant_user_id": "applicant-1",
        "applicant_name": "Acme",
        "proposed_investment_cents": 150_000_000,
    }
    validate_error(api.create_application(payload, APPLICANT), ApiErrorId.ERR_VALIDATION)


def test_unauthenticated_request_returns_401(api):
    """PRD §2.1: "If either header is missing or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/errors/unauthenticated_request_returns_401
    """
    payload = create_application_payload(NONEXISTENT_UUID)
    validate_error(api.create_application(payload, {}), ApiErrorId.ERR_UNAUTHENTICATED)


def test_create_application_unknown_program_returns_404(api):
    """PRD §2.4: "an unknown program yields `ERR_PROGRAM_NOT_FOUND`". A create body naming a
    program_id that does not resolve is rejected.

    Design: Corner/errors/create_application_unknown_program_returns_404
    """
    payload = create_application_payload(NONEXISTENT_UUID)
    validate_error(api.create_application(payload, APPLICANT), ApiErrorId.ERR_PROGRAM_NOT_FOUND)


def test_applicant_cannot_create_program_returns_403(api):
    """PRD §2.1: "If the headers are present but the role is not permitted to perform the
    requested operation under the matrix below, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." Only a ProgramDirector may create a program.

    Design: Corner/rbac/applicant_cannot_create_program_returns_403
    """
    validate_error(api.create_program(create_program_payload(), APPLICANT), ApiErrorId.ERR_UNAUTHORIZED)


def test_publicviewer_cannot_read_applications_returns_403(api):
    """PRD §2.1: "A `PublicViewer` is a read-only transparency consumer limited to programs,
    published disclosures, and the portfolio dashboard."

    Design: Corner/rbac/publicviewer_cannot_read_applications_returns_403
    """
    validate_error(api.list_applications(PUBLIC), ApiErrorId.ERR_UNAUTHORIZED)


def test_activate_already_active_returns_invalid_state(api):
    """PRD §3.3: "Activating, declaring default, or otherwise transitioning an agreement from
    an illegal state yields `ERR_AGREEMENT_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_returns_invalid_state
    """
    ctx = setup_active_agreement(app_overrides={"but_for_attested": True})
    validate_error(api.activate_agreement(ctx["agreement"]["id"], DIRECTOR),
                   ApiErrorId.ERR_AGREEMENT_INVALID_STATE)


def test_approve_draft_application_returns_invalid_state(api):
    """PRD §3.2: "An attempt to submit, start review, approve, or deny from a state where
    that transition is not legal yields `ERR_APPLICATION_INVALID_STATE`."

    Design: Corner/state_machines/approve_draft_application_returns_invalid_state
    """
    prog = create_program()
    app = create_application(prog["id"], but_for_attested=True)  # DRAFT
    validate_error(api.approve_application(app["id"], DIRECTOR),
                   ApiErrorId.ERR_APPLICATION_INVALID_STATE)
