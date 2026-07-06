"""State-machine breadth: initial states, invalid transitions, terminal lockdown,
guarded transitions, side effects.

Translates the corner `state_machines` section instances.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    create_program, create_camera, add_calibration, create_owner,
    capture_citation, review_to_cited,
    create_camera_payload, create_citation_payload, review_payload,
    setup_cited_citation,
    TEST_USERS, make_review_officer_headers,
)

PA = TEST_USERS["program_admin_headers"]
RO = make_review_officer_headers("ro-1")


def test_review_already_reviewed_citation_invalid_state(api):
    """PRD §3.3: "Both decisions require the citation to be in `PENDING_REVIEW`;
    otherwise the review is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/review_already_reviewed_citation_invalid_state
    """
    ctx = setup_cited_citation()
    cit = ctx["citation"]
    res = api.review_citation(cit["id"], review_payload("REJECT"), RO)
    validate_error(res, "ERR_INVALID_STATE")
    unchanged = get_success_data(api.get_citation(cit["id"], PA))
    assert unchanged["status"] == "CITED"


def test_new_citation_initial_state_pending_review(api):
    """PRD §3.3: "A successful capture creates a **Citation** in `PENDING_REVIEW`
    status; at this point the citation's `registered_owner_id` is still null, and the
    money fields have not yet been computed."

    Design: Corner/state_machines/new_citation_initial_state_pending_review
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    citation = capture_citation(program["id"], camera["id"])
    assert citation["status"] == "PENDING_REVIEW"


def test_terminal_rejected_citation_cannot_be_voided(api):
    """PRD §3.8: "A void is permitted only while the citation is in `PENDING_REVIEW`,
    `CITED`, or `DELINQUENT`; from any other state it is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_rejected_citation_no_transitions
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    citation = capture_citation(program["id"], camera["id"])
    rejected = get_success_data(
        api.review_citation(citation["id"], review_payload("REJECT"), RO))
    assert rejected["status"] == "REJECTED"
    res = api.void_citation(citation["id"], PA)
    validate_error(res, "ERR_INVALID_STATE")


def test_reactivate_active_camera_invalid_state(api):
    """PRD §3.1: "a suspended camera may be reactivated, transitioning `SUSPENDED →
    ACTIVE`... Each of these actions requires the camera to be in the stated
    originating state; attempting one from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reactivate_active_camera_invalid_state
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    assert camera["status"] == "ACTIVE"
    res = api.reactivate_camera(camera["id"], PA)
    validate_error(res, "ERR_INVALID_STATE")


def test_capture_on_suspended_camera_no_violation(api):
    """PRD §3.3: "Capture is only permitted when the camera's `status` is `ACTIVE` at
    handling time; a capture against a non-active camera is rejected with
    `ERR_NO_VIOLATION` (HTTP 422)."

    Design: Corner/state_machines/capture_on_suspended_camera_no_violation
    """
    program = create_program()
    camera = create_camera(program["id"], camera_type="RED_LIGHT")
    get_success_data(api.suspend_camera(camera["id"], PA))
    res = api.create_citation(
        create_citation_payload(program["id"], camera["id"],
                                captured_plate_number="ABC123"),
        RO)
    validate_error(res, "ERR_NO_VIOLATION")


