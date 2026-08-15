"""Feeding-trial protocol lifecycle (PRD §2.10, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_trial_protocol,
    setup_trial_protocol,
    validate_error,
    validate_success,
)


def test_trial_enrollment_accumulates_enrolled_count(api, trial_coordinator_headers):
    """PRD §3.4: "A new protocol starts in `PLANNED` with `enrolled_count` and
    `completed_count` at zero"
    PRD §3.4: "While the protocol is `ENROLLING`, the `TrialCoordinator` records
    enrollment events; each event carries an `enrolled_delta` that is added to the
    running `enrolled_count`."

    Design: Corner/state_machines/trial_enrollment_accumulates_enrolled_count
    """
    ctx = setup_trial_protocol(target_state="ENROLLING", enroll_deltas=[])
    protocol = ctx["protocol"]
    assert protocol["status"] == "ENROLLING"

    created = validate_success(
        api.get_trial_protocol(protocol["id"], trial_coordinator_headers)
    )
    assert created["enrolled_count"] == 0

    first = validate_success(api.enroll(protocol["id"], {"enrolled_delta": 3}, trial_coordinator_headers))
    assert_trial_protocol(first)
    assert first["enrolled_count"] == 3
    second = validate_success(api.enroll(protocol["id"], {"enrolled_delta": 5}, trial_coordinator_headers))
    assert second["enrolled_count"] == 8


def test_trial_created_in_planned_with_zero_counts(api):
    """PRD §3.4: "A new protocol starts in `PLANNED` with `enrolled_count` and
    `completed_count` at zero"

    Design: Corner/state_machines/trial_enrollment_accumulates_enrolled_count
    """
    ctx = setup_trial_protocol(target_state="PLANNED")
    protocol = ctx["protocol"]
    assert_trial_protocol(protocol)
    assert protocol["status"] == "PLANNED"
    assert protocol["enrolled_count"] == 0
    assert protocol["completed_count"] == 0


def test_trial_start_before_full_enrollment_fails(api, trial_coordinator_headers):
    """PRD §3.4: "Starting the trial moves the protocol from `ENROLLING` to
    `RUNNING` and requires full enrollment — the recorded `enrolled_count` must be
    at least the planned `animal_count`; otherwise the request is rejected with
    `ERR_TRIAL_NOT_FULLY_ENROLLED` (HTTP 422)."

    Design: Corner/state_machines/trial_start_before_full_enrollment_fails
    """
    ctx = setup_trial_protocol(target_state="ENROLLING", enroll_deltas=[4])
    assert ctx["protocol"]["enrolled_count"] == 4
    resp = api.start_trial(ctx["protocol"]["id"], trial_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_TRIAL_NOT_FULLY_ENROLLED.value)
    current = validate_success(api.get_trial_protocol(ctx["protocol"]["id"], trial_coordinator_headers))
    assert current["status"] == "ENROLLING"


def test_trial_verdict_from_running_fails_invalid_state(api, qa_approver_headers):
    """PRD §3.4: "Recording a verdict routes on the recomputed ratio: a
    `completion_ratio` of 0.75 or higher moves the protocol from `ANALYSIS` to
    `PASSED`, while a ratio below 0.75 moves it to `FAILED`."
    PRD §2.10: "Fourth, transition validity: the requested action must correspond
    to a transition that exists from the resource's current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/trial_verdict_from_running_fails_invalid_state
    """
    ctx = setup_trial_protocol(target_state="RUNNING")
    resp = api.record_verdict(ctx["protocol"]["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    current = validate_success(api.get_trial_protocol(ctx["protocol"]["id"], qa_approver_headers))
    assert current["status"] == "RUNNING"


def test_trial_abort_from_running_succeeds_then_terminal(api, qa_approver_headers):
    """PRD §3.4: "Separately, a `QAApprover` may abort a protocol mid-run, moving
    it from `RUNNING` to `ABORTED`. `PASSED`, `FAILED`, and `ABORTED` are terminal."
    PRD §2.10: "a resource already in a terminal state accepts no further
    transitions at all and rejects them with `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/trial_abort_from_running_succeeds_then_terminal
    """
    ctx = setup_trial_protocol(target_state="RUNNING")
    aborted = validate_success(api.abort_trial(ctx["protocol"]["id"], qa_approver_headers))
    assert aborted["status"] == "ABORTED"

    resp = api.record_verdict(ctx["protocol"]["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value)
