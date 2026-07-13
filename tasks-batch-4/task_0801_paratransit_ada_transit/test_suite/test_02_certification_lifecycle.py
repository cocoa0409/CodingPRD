"""Eligibility certification lifecycle: certify/deny/complete guards, the
denial-appeal-reassessment cycle, and the duplicate-application constraint.

Queue A (Difficulty): non_linear_state_machine / eligibility_denial_appeal cycle.
Queue B (Corner): state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_application_payload, create_assessment_payload, complete_assessment_payload,
)
import test_helpers as th

SPECIALIST = TEST_USERS["specialist_headers"]


# ==========================================================================
# Difficulty A — eligibility denial -> appeal -> reassessment cycle
# ==========================================================================
def _denied_appealed_application(api):
    """Rider whose application is assessed FAIL, denied, then appealed (APPEALED)."""
    base = th.assessed_application(api, outcome="FAIL", clock="2026-06-01T00:00:00Z")
    app_id = base["application"]["id"]
    api.deny_application(app_id, SPECIALIST)
    api.appeal_application(app_id, SPECIALIST)
    base["app_id"] = app_id
    return base


def test_appeal_then_schedule_reopens_to_assessment_scheduled(api):
    """PRD §3.2: "Scheduling an in-person functional assessment is permitted when the
    parent application is in either `SUBMITTED` or `APPEALED`; the act creates a
    `FunctionalAssessment` in `SCHEDULED` and advances the application from `SUBMITTED`
    to `ASSESSMENT_SCHEDULED` (or, when re-entering after an appeal, from `APPEALED` to
    `ASSESSMENT_SCHEDULED`)."

    Design: Difficulty/non_linear_state_machine/eligibility_denial_appeal_reassessment_cycle_increments_appeal_count
    """
    base = _denied_appealed_application(api)
    resp = api.create_assessment(create_assessment_payload(base["app_id"],
                                                           scheduled_at="2026-06-10T10:00:00Z"), SPECIALIST)
    validate_success(resp, 201)
    app = validate_success(api.get_application(base["app_id"], SPECIALIST))
    assert app["status"] == "ASSESSMENT_SCHEDULED"


def test_appeal_increments_appeal_count(api):
    """PRD §3.3: "Appeal is permitted only when the application's `status` is `DENIED`;
    it advances the application from `DENIED` to `APPEALED` and increments `appeal_count`
    by one."

    Design: Difficulty/non_linear_state_machine/eligibility_denial_appeal_reassessment_cycle_increments_appeal_count
    """
    base = _denied_appealed_application(api)
    app = validate_success(api.get_application(base["app_id"], SPECIALIST))
    assert app["status"] == "APPEALED"
    assert app["appeal_count"] == 1


# ==========================================================================
# Corner B — state-machine guards
# ==========================================================================
def test_certify_submitted_application_rejected(api):
    """PRD §3.3: "Certifying an application is permitted only when its `status` is
    `ASSESSED` and its `assessment_outcome` is either `PASS_UNCONDITIONAL` or
    `PASS_CONDITIONAL`; otherwise the request is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/certify_from_submitted_returns_invalid_state
    """
    base = th.submitted_application(api)
    resp = api.certify_application(base["application"]["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_certify_failed_assessment_rejected(api):
    """PRD §3.3: "Certifying an application is permitted only when its `status` is
    `ASSESSED` and its `assessment_outcome` is either `PASS_UNCONDITIONAL` or
    `PASS_CONDITIONAL`; otherwise the request is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/certify_failed_assessment_returns_invalid_state
    """
    base = th.assessed_application(api, outcome="FAIL")
    resp = api.certify_application(base["application"]["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_deny_passing_assessment_rejected(api):
    """PRD §3.3: "Denying an application is the symmetric branch: it is permitted only
    when the `status` is `ASSESSED` and the `assessment_outcome` is `FAIL`, and it
    advances the application from `ASSESSED` to `DENIED`, leaving the rider's
    `eligibility_status` unchanged (the rider remains `UNCERTIFIED` or `EXPIRED`). Any
    other combination is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/deny_passing_assessment_returns_invalid_state
    """
    base = th.assessed_application(api, outcome="PASS_UNCONDITIONAL")
    resp = api.deny_application(base["application"]["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_assessment_twice_rejected(api):
    """PRD §3.2: "Completion is permitted only when the assessment being completed
    belongs to the referenced application, the assessment's `status` is `SCHEDULED`, and
    the parent application's `status` is `ASSESSMENT_SCHEDULED`; otherwise the request is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_assessment_twice_returns_invalid_state
    """
    base = th.submitted_application(api)
    fa = validate_success(api.create_assessment(
        create_assessment_payload(base["application"]["id"]), SPECIALIST), 201)
    validate_success(api.complete_assessment(
        fa["id"], complete_assessment_payload(outcome="PASS_UNCONDITIONAL"), SPECIALIST))
    resp = api.complete_assessment(
        fa["id"], complete_assessment_payload(outcome="PASS_UNCONDITIONAL"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_dispatch_planned_run_rejected(api):
    """PRD §3.7: "Opening is permitted only from `PLANNED` and dispatching only from
    `OPEN`; otherwise the transition is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/dispatch_planned_run_returns_invalid_state
    """
    zone = th.create_zone_a(api)
    run = th.create_run(api, zone["id"])
    resp = api.dispatch_run(run["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_completed_trip_rejected(api):
    """PRD §2.6: "The generic state guard — the target resource must be in a state that
    permits the requested transition — surfaces as `ERR_INVALID_STATE` (HTTP 409) on
    every state-changing endpoint."
    PRD §3.9: "A trip's lifecycle states are `REQUESTED`, `OFFERED`, `COUNTERED`,
    `SCHEDULED`, `EN_ROUTE`, `PICKED_UP`, `COMPLETED`, `CANCELLED`, `LATE_CANCELLED`,
    `NO_SHOW`, and `CANCELLED_BY_SYSTEM`, of which the last five are terminal."

    Design: Corner/state_machines/cancel_completed_trip_returns_invalid_state
    """
    base = th.scenario_picked_up_trip(api)
    trip_id = base["trip"]["id"]
    zone_id = base["zone_a"]["id"]
    validate_success(api.dropoff_trip(
        trip_id, {"actual_dropoff_at": "2026-06-05T09:20:00Z", "actual_dropoff_zone_id": zone_id},
        TEST_USERS["driver_headers"]))
    resp = api.cancel_trip(trip_id, th.make_rider_headers(base["rider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    trip = validate_success(api.get_trip(trip_id, TEST_USERS["driver_headers"]))
    assert trip["status"] == "COMPLETED"


def test_duplicate_active_application_rejected(api):
    """PRD §3.1: "A rider may hold only one open application at a time: if the rider
    already has a non-terminal application — one in any state other than the terminal
    `CERTIFIED` — a new submission is rejected with `ERR_DUPLICATE_ACTIVE_APPLICATION`
    (HTTP 409)."

    Design: Corner/state_machines/duplicate_active_application_returns_conflict
    """
    base = th.submitted_application(api)
    resp = api.create_application(create_application_payload(base["rider"]["id"]), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION.value)
