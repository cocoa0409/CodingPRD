"""Applicant intake, the eligibility review cycle, and submission gates.

Queue A: application_cyclic_review_loop, submit_residency_beats_window.
Queue B: resubmit invalid-state, vacancy close, wrong-owner resubmit, window closed.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_board_payload, create_seat_payload, create_vacancy_payload,
    create_applicant_payload, create_application_payload,
    TEST_USERS, make_applicant_headers,
    new_board, new_seat, new_applicant, new_vacancy, eligible_application,
    set_clock, api_client,
)

CLERK = TEST_USERS["clerk_headers"]


def _returned_application():
    """Board/seat/applicant/vacancy -> submit -> start-review -> return-for-info.
    Returns (application, applicant)."""
    board = new_board()
    seat = new_seat(board["id"])
    applicant = new_applicant()
    vacancy = new_vacancy(seat["id"])
    app = validate_success(api_client.create_application(
        create_application_payload(applicant["id"], vacancy["id"]),
        make_applicant_headers(applicant["id"])), 201)
    api_client.start_review(app["id"], CLERK)
    api_client.return_for_info(app["id"], {"notes": "more info"}, CLERK)
    return app, applicant


# ─── Queue A: application_cyclic_review_loop ───────────────────
def test_application_cycles_review_twice(api):
    """PRD §3.2: "From `UNDER_REVIEW`, the clerk may return the application for more
    information ... which moves it to `RETURNED_FOR_INFO` and increments `return_count`
    by 1."
    PRD §3.2: "The application may bounce between `UNDER_REVIEW` and `RETURNED_FOR_INFO`
    any number of times."

    Design: Difficulty/non_linear_state_machine/application_cyclic_review_loop
    """
    app, applicant = _returned_application()
    ah = make_applicant_headers(applicant["id"])
    validate_success(api.resubmit_application(app["id"], {}, ah), 200)
    validate_success(api.return_for_info(app["id"], {"notes": "need voter card"}, CLERK), 200)
    final = validate_success(api.resubmit_application(app["id"], {}, ah), 200)
    assert final["status"] == "UNDER_REVIEW"
    assert final["return_count"] == 2


def test_application_single_cycle_increments_return_count(api):
    """PRD §3.2: "the clerk may return the application for more information ... which
    moves it to `RETURNED_FOR_INFO` and increments `return_count` by 1. The owning
    applicant then resubmits ... which moves the application from `RETURNED_FOR_INFO`
    back to `UNDER_REVIEW`".

    Design: Difficulty/non_linear_state_machine/application_cyclic_review_loop
    """
    app, applicant = _returned_application()
    returned = validate_success(api.get_application(app["id"], CLERK), 200)
    assert returned["status"] == "RETURNED_FOR_INFO"
    assert returned["return_count"] == 1
    back = validate_success(
        api.resubmit_application(app["id"], {}, make_applicant_headers(applicant["id"])), 200)
    assert back["status"] == "UNDER_REVIEW"
    assert back["return_count"] == 1


# ─── Queue A: submit_residency_beats_window ────────────────────
def test_submit_residency_beats_closed_window(api):
    """PRD §3.2: "On submission, two business checks run in order: the residency check
    first, then the application-window check."
    PRD §3.2: "A submission that fails residency, or whose `residency_attested` is
    false, is rejected with `ERR_RESIDENCY_REQUIREMENT_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/submit_residency_beats_window
    """
    set_clock("2026-06-10T00:00:00Z")
    board = new_board()
    seat = new_seat(board["id"], seat_category="DISTRICT",
                    residency_requirement="IN_JURISDICTION")
    applicant = new_applicant(full_name="Carl Nolan", email="carl@x.com",
                              residence_district="D9", resides_in_jurisdiction=False)
    vacancy = new_vacancy(seat["id"], application_deadline="2026-06-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant["id"], vacancy["id"], residency_attested=True),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_RESIDENCY_REQUIREMENT_NOT_MET")


def test_submit_unattested_residency_beats_closed_window(api):
    """PRD §3.2: "the residency check first, then the application-window check ... A
    submission that fails residency, or whose `residency_attested` is false, is rejected
    with `ERR_RESIDENCY_REQUIREMENT_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/submit_residency_beats_window
    """
    set_clock("2026-06-10T00:00:00Z")
    board = new_board()
    seat = new_seat(board["id"], residency_requirement="IN_JURISDICTION")
    applicant = new_applicant()
    vacancy = new_vacancy(seat["id"], application_deadline="2026-06-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant["id"], vacancy["id"], residency_attested=False),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_RESIDENCY_REQUIREMENT_NOT_MET")


# ─── Queue B ───────────────────────────────────────────────────
def test_resubmit_eligible_application_invalid_state(api):
    """PRD §3.2: "Each transition requires the application to be in the state the
    transition starts from; otherwise the request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/resubmit_eligible_application_invalid_state
    """
    board = new_board()
    seat = new_seat(board["id"])
    applicant = new_applicant()
    vacancy = new_vacancy(seat["id"])
    app = eligible_application(vacancy["id"], applicant["id"])
    assert app["status"] == "ELIGIBLE"
    res = api.resubmit_application(app["id"], {}, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_vacancy_close_open_to_closed(api):
    """PRD §3.1: "A clerk may close an open vacancy without filling it, moving its
    `status` from `OPEN` to `CLOSED`."

    Design: Corner/state_machines/vacancy_close_open_to_closed
    """
    board = new_board()
    seat = new_seat(board["id"])
    vacancy = new_vacancy(seat["id"])
    closed = validate_success(api.close_vacancy(vacancy["id"], CLERK), 200)
    assert closed["status"] == "CLOSED"


def test_resubmit_by_wrong_applicant_not_resource_owner(api):
    """PRD §3.2: "the applicant may only resubmit their own application, and an applicant
    acting on an application they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/resubmit_by_wrong_applicant_not_resource_owner
    """
    app, applicant = _returned_application()
    other = new_applicant(full_name="Ben Cole", email="ben@x.com")
    res = api.resubmit_application(app["id"], {}, make_applicant_headers(other["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_application_window_closed_alone(api):
    """PRD §3.2: "a submission after the deadline is rejected with
    `ERR_APPLICATION_WINDOW_CLOSED`."

    Design: Corner/validations/application_window_closed_alone
    """
    set_clock("2026-06-10T00:00:00Z")
    board = new_board()
    seat = new_seat(board["id"])  # residency NONE -> residency satisfied
    applicant = new_applicant()
    vacancy = new_vacancy(seat["id"], application_deadline="2026-06-01T00:00:00Z")
    res = api.create_application(
        create_application_payload(applicant["id"], vacancy["id"], residency_attested=True),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_APPLICATION_WINDOW_CLOSED")
