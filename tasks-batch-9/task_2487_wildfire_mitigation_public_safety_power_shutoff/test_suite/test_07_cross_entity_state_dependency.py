"""Writes whose local preconditions all hold and are still refused, because the gate
lives on a different entity: the governing event, the hardened circuit, or the plan-year
portfolio behind a filing."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CIRCUIT_POSTURE_LOCKED,
    ERR_EVENT_NOT_IN_RESTORATION,
    ERR_FILING_METRICS_INCOMPLETE,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_circuit_state,
    assert_event_dimensions,
    assert_filing_metrics,
    assert_filing_tracks,
    assert_integer,
)
from test_helpers.fixtures import (
    PATROL_DONE_AT,
    PATROL_START_AT,
    build_active_event,
    build_advance_dispatched_event,
    build_armed_event,
    build_scoped_event,
    book_project,
    cancel_event,
    declare_all_clear,
    open_filing,
    read_circuit,
    read_event,
    read_filing,
    read_patrol,
    read_project,
    register_circuit,
    review_project,
    schedule_patrol,
    start_patrol,
    submit_filing,
    submit_project,
)
from test_helpers.test_users import PLANNER_HEADERS, SUPERVISOR_HEADERS
from test_helpers.types import HftdTier, ProgramType, ReviewDecision

CANCELLATION_REASON = "forecast improved"


def _active_event_with_a_scheduled_patrol():
    """EV-1 is ACTIVE with all three circuits DE_ENERGIZED and a GROUND assignment booked
    on ALPHA, so both of the assignment's own preconditions are satisfied."""
    ctx = build_active_event()
    ctx["patrol_alpha"] = schedule_patrol(
        ctx["event_id"],
        ctx["alpha"]["id"],
        PATROL_START_AT,
        PATROL_DONE_AT,
        patrol_lead_user_id="crew_lead_1",
    )
    return ctx


def _armed_event_with_a_draft_project_on_alpha():
    """MP-CC-2 is booked on ALPHA while the circuit is still ENERGIZED, and only then is
    the event armed."""
    ctx = build_scoped_event()
    ctx["project"] = book_project(
        ctx["alpha"]["id"],
        project_code="MP-CC-2",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=2.0,
        unit_cost_per_mile_cents=1250000,
    )
    ctx = build_advance_dispatched_event(ctx)
    return build_armed_event(ctx)


def _filing_whose_only_project_is_still_submitted():
    """WMP-2026 is a well-formed DRAFT, but the sole 2026 project sits at SUBMITTED and so
    qualifies for nothing."""
    delta = register_circuit(
        circuit_code="DELTA",
        district_code="D-WEST",
        hftd_tier=HftdTier.NON_HFTD.value,
        overhead_miles=4.0,
        equipment_condition_index=90,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    project = book_project(
        delta["id"],
        project_code="MP-UG-1",
        program_type=ProgramType.UNDERGROUNDING.value,
        planned_miles=3.0,
        unit_cost_per_mile_cents=9000000,
    )
    project = submit_project(project["id"])
    filing = open_filing(filing_code="WMP-2026", plan_year=2026)
    return delta, project, filing


# --------------------------------------------------------------------------
# (PatrolAssignment, PSPSEvent)
# --------------------------------------------------------------------------
def test_a_patrol_cannot_start_while_the_weather_is_still_running():
    """The assignment is SCHEDULED and its circuit is DE_ENERGIZED, yet the start is
    refused because meteorology has not declared the window over.

    "Two cross-entity conditions also apply: the governing event's `scope_status` must be
    `RESTORING`, otherwise `ERR_EVENT_NOT_IN_RESTORATION`, and the circuit must be in one
    of the three post-shutoff energization phases, otherwise
    `ERR_CIRCUIT_NOT_DE_ENERGIZED`."

    Design: Difficulty/cross_entity_state_dependency/patrol_start_requires_event_in_restoration
    """
    ctx = _active_event_with_a_scheduled_patrol()

    response = api_client.start_patrol(ctx["patrol_alpha"]["id"], SUPERVISOR_HEADERS)

    validate_error(response, ERR_EVENT_NOT_IN_RESTORATION, 409)
    assignment = read_patrol(ctx["patrol_alpha"]["id"])
    assert assignment["status"] == "SCHEDULED"
    assert assignment["started_at"] is None
    assert_event_dimensions(read_event(ctx["event_id"]), scope_status="ACTIVE")
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="DE_ENERGIZED",
        risk_posture="LOCKED",
    )


def test_the_all_clear_is_what_unblocks_the_very_same_start():
    """Nothing about the assignment changes; the event moving to RESTORING is what lets
    the identical call through, and the start then drives the circuit.

    "The start drives the circuit too: a circuit at `DE_ENERGIZED` advances to
    `PATROL_IN_PROGRESS`, and a circuit already at `CLEARED_FOR_RESTORE` also advances to
    `PATROL_IN_PROGRESS` — that second edge is the repair back-edge described below."

    Design: Difficulty/cross_entity_state_dependency/patrol_start_requires_event_in_restoration
    """
    ctx = _active_event_with_a_scheduled_patrol()
    refused = api_client.start_patrol(ctx["patrol_alpha"]["id"], SUPERVISOR_HEADERS)
    validate_error(refused, ERR_EVENT_NOT_IN_RESTORATION, 409)

    restoring = declare_all_clear(ctx["event_id"])
    assert_event_dimensions(restoring, scope_status="RESTORING")

    assert read_patrol(ctx["patrol_alpha"]["id"])["status"] == "SCHEDULED"

    started = start_patrol(ctx["patrol_alpha"]["id"])

    assert started["status"] == "IN_PROGRESS"
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="PATROL_IN_PROGRESS",
        risk_posture="LOCKED",
    )


# --------------------------------------------------------------------------
# (MitigationProject, Circuit)
# --------------------------------------------------------------------------
def test_a_draft_package_cannot_be_submitted_on_a_staged_circuit():
    """The project's own state machine admits the edge out of DRAFT, but ALPHA has been
    staged for the shutoff and its posture is the gate.

    "A `GridPlanner` submits a project from either `DRAFT` or `REVISION_REQUESTED`,
    advancing it to `SUBMITTED`; submission from any other status is refused with
    `ERR_PROJECT_INVALID_STATE`, and submission is likewise refused with
    `ERR_CIRCUIT_POSTURE_LOCKED` when the circuit's posture has become `LOCKED` since
    booking."

    Design: Difficulty/cross_entity_state_dependency/mitigation_submit_blocked_by_locked_circuit_posture
    """
    ctx = _armed_event_with_a_draft_project_on_alpha()

    response = api_client.submit_mitigation_project(
        ctx["project"]["id"], PLANNER_HEADERS
    )

    validate_error(response, ERR_CIRCUIT_POSTURE_LOCKED, 409)
    project = read_project(ctx["project"]["id"])
    assert project["status"] == "DRAFT"
    assert_2dp(project["risk_reduction_score"], 1.86)
    assert_integer(project["budget_cents"], 2500000)
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="DE_ENERGIZATION_PENDING",
        risk_posture="LOCKED",
    )


def test_cancelling_the_shutoff_returns_the_circuit_and_unblocks_the_package():
    """Cancelling from ARMED reverts ALPHA out of LOCKED, and the previously refused
    submission then succeeds untouched.

    "Cancelling from `ARMED` does all of that **and** performs the compensation proper:
    every circuit sitting at `DE_ENERGIZATION_PENDING` for this event reverts to
    `ENERGIZED` with its `risk_posture` recomputed out of `LOCKED`, which must restore the
    energized-customer total of §2.11 to exactly its pre-arm value; every resource center
    already `ACTIVATED` for the event is demobilized; and any patrol assignment on the
    event still at `SCHEDULED` or `IN_PROGRESS` moves to `ABORTED`."

    Design: Difficulty/cross_entity_state_dependency/mitigation_submit_blocked_by_locked_circuit_posture
    """
    ctx = _armed_event_with_a_draft_project_on_alpha()
    refused = api_client.submit_mitigation_project(ctx["project"]["id"], PLANNER_HEADERS)
    validate_error(refused, ERR_CIRCUIT_POSTURE_LOCKED, 409)

    cancelled = cancel_event(ctx["event_id"], CANCELLATION_REASON)
    assert cancelled["scope_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == CANCELLATION_REASON
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="ENERGIZED",
        risk_posture="EXTREME",
    )

    submitted = submit_project(ctx["project"]["id"])

    assert submitted["status"] == "SUBMITTED"
    assert_2dp(submitted["risk_reduction_score"], 1.86)


# --------------------------------------------------------------------------
# (WildfirePlanFiling, MitigationProject) across the plan-year join
# --------------------------------------------------------------------------
def test_a_filing_with_only_a_submitted_project_has_nothing_to_report():
    """The filing is a clean DRAFT, but its plan year holds no qualifying project, so the
    submission is refused.

    "Filing with the regulator advances a filing from `DRAFT`, or from
    `DEFICIENCY_ISSUED` on a cure round, to `SUBMITTED`; a filing in any other status
    refuses the submission with `ERR_FILING_INVALID_STATE`, and a filing whose
    `qualifying_project_count` is zero refuses it with `ERR_FILING_METRICS_INCOMPLETE` —
    there is nothing to report."

    Design: Difficulty/cross_entity_state_dependency/filing_submit_requires_qualifying_mitigation_project
    """
    delta, project, filing = _filing_whose_only_project_is_still_submitted()

    response = api_client.submit_plan_filing(filing["id"], PLANNER_HEADERS)

    validate_error(response, ERR_FILING_METRICS_INCOMPLETE, 422)
    unchanged = read_filing(filing["id"])
    assert_filing_tracks(
        unchanged,
        status="DRAFT",
        safety_review_state="PENDING",
        fiscal_review_state="PENDING",
    )
    assert_filing_metrics(unchanged, qualifying_project_count=0)
    assert read_project(project["id"])["status"] == "SUBMITTED"


def test_approving_that_project_brings_the_plan_year_into_the_qualifying_set():
    """Approval alone moves the project into the qualifying statuses, and the identical
    filing submission is then admitted with a count of one.

    "The qualifying projects are the mitigation projects whose `plan_year` equals the
    filing's `plan_year` and whose `status` is `APPROVED`, `IN_EXECUTION`, `SUSPENDED`, or
    `COMPLETED`; projects in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, or `WITHDRAWN`
    are excluded entirely."

    Design: Difficulty/cross_entity_state_dependency/filing_submit_requires_qualifying_mitigation_project
    """
    delta, project, filing = _filing_whose_only_project_is_still_submitted()
    refused = api_client.submit_plan_filing(filing["id"], PLANNER_HEADERS)
    validate_error(refused, ERR_FILING_METRICS_INCOMPLETE, 422)

    approved = review_project(
        project["id"], ReviewDecision.APPROVE.value, "undergrounding plan accepted"
    )
    assert approved["status"] == "APPROVED"

    submitted = submit_filing(filing["id"])

    assert_filing_tracks(
        submitted,
        status="SUBMITTED",
        safety_review_state="PENDING",
        fiscal_review_state="PENDING",
        safety_reviewer_user_id=None,
        fiscal_reviewer_user_id=None,
        deficiency_round_count=0,
    )
    assert_filing_metrics(
        submitted,
        qualifying_project_count=1,
        covered_conductor_miles_reported=0.0,
        underground_miles_reported=0.0,
        psps_event_count=0,
        customer_minutes_interrupted=0,
        avg_notification_lead_minutes=0.00,
    )
    assert_1dp(read_project(project["id"])["completed_miles"], 0.0)
