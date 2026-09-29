"""Where each machine starts, which edges are wired, what an edge cascades onto its
neighbours, and how a terminal or already-decided state turns a repeat call away."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_BATCH_ALREADY_DISPATCHED,
    ERR_EVENT_NOT_ACTIVE,
    ERR_EVENT_NOT_CANCELLABLE,
    ERR_EVENT_NOT_SCOPED,
    ERR_EVENT_TERMINAL,
    ERR_FILING_INVALID_STATE,
    ERR_PATROL_INVALID_STATE,
    ERR_PROJECT_INVALID_STATE,
    ERR_REVIEW_TRACK_ALREADY_DECIDED,
    ERR_SCOPE_ALREADY_EXCLUDED,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_batch_outcome,
    assert_center_state,
    assert_circuit_state,
    assert_event_dimensions,
    assert_filing_metrics,
    assert_filing_tracks,
    assert_hardening_ledger,
    assert_impact_counts,
    assert_instant,
    assert_integer,
    assert_scope_counts,
    assert_scope_row,
    assert_versioned_entity,
    scope_row_for,
)
from test_helpers.fixtures import (
    ONSET_AT,
    PATROL_DONE_AT,
    PATROL_START_AT,
    RESTORE_CHARLIE_AT,
    build_advance_dispatched_event,
    build_approved_project,
    build_armed_event,
    build_closed_event,
    build_feeder_chain,
    build_imminent_dispatched_event,
    build_active_event,
    build_restoring_event,
    build_scoped_event,
    complete_patrol,
    dispatch_batch,
    exclude_scope_row,
    move_clock,
    open_event,
    open_filing,
    plan_batch,
    read_circuit,
    read_event,
    read_filing,
    read_patrol,
    read_project,
    read_records,
    read_scope_rows,
    record_completion,
    register_circuit,
    review_filing,
    review_project,
    schedule_patrol,
    scope_event,
    start_patrol,
    submit_filing,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    ENGINEER_HEADERS,
    INSPECTOR_HEADERS,
    LIAISON_HEADERS,
    OFFICER_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_ALPHA,
    SUPERVISOR_HEADERS,
)
from test_helpers.types import (
    FilingDecision,
    NotificationStage,
    ProgramType,
    ReviewDecision,
    ReviewTrack,
)

ADVANCE_24H_SEND_AT = "2026-08-14T18:00:00Z"
FOLLOW_UP_START_AT = "2026-08-17T01:01:00Z"
FOLLOW_UP_END_AT = "2026-08-17T02:00:00Z"
RE_ENERGIZE_AT = "2026-08-17T01:30:00Z"
FIRST_EXCLUSION = "first exclusion"
ROUND_ONE_NOTE = "round 1 - risk model inputs unsourced"
ROUND_TWO_NOTE = "round 2 - still unsourced"
ROUND_THREE_NOTE = "round 3 - unit costs unsupported"


def _scoped_chain_with_charlie_excluded():
    """EV-1 SCOPED over the chain with CHARLIE held out by the transmission engineer, so
    the event scores 11.18 over two confirmed rows."""
    ctx = build_scoped_event()
    rows = read_scope_rows(ctx["event_id"])
    ctx["charlie_scope"] = scope_row_for(rows, ctx["charlie"]["id"])
    exclude_scope_row(ctx["charlie_scope"]["id"], FIRST_EXCLUSION)
    return ctx


def _restoring_chain_with_two_alpha_patrols():
    """ALPHA carries a completed patrol and a second assignment still SCHEDULED for a
    later window, while BRAVO and CHARLIE each hold one untouched assignment."""
    ctx = build_restoring_event()
    ctx["pa_alpha"] = schedule_patrol(
        ctx["event_id"], ctx["alpha"]["id"], PATROL_START_AT, PATROL_DONE_AT
    )
    ctx["pa_alpha_2"] = schedule_patrol(
        ctx["event_id"],
        ctx["alpha"]["id"],
        FOLLOW_UP_START_AT,
        FOLLOW_UP_END_AT,
        patrol_lead_user_id="crew_lead_2",
    )
    ctx["pa_bravo"] = schedule_patrol(
        ctx["event_id"], ctx["bravo"]["id"], PATROL_START_AT, PATROL_DONE_AT
    )
    ctx["pa_charlie"] = schedule_patrol(
        ctx["event_id"], ctx["charlie"]["id"], PATROL_START_AT, PATROL_DONE_AT
    )
    move_clock(PATROL_START_AT)
    start_patrol(ctx["pa_alpha"]["id"])
    move_clock(PATROL_DONE_AT)
    complete_patrol(ctx["pa_alpha"]["id"], 7.0)
    return ctx


def _withdrawn_covered_conductor_project():
    """MP-CC executed to its full 4.0 miles and then withdrawn, so the ledger is back at
    zero and the project is terminal."""
    alpha = register_circuit(circuit_code="ALPHA")
    project = build_approved_project(
        alpha["id"],
        project_code="MP-CC",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        unit_cost_per_mile_cents=1250000,
    )
    project = record_completion(
        project["id"], 4.0, "2026-07-01T00:00:00Z", read_circuit(alpha["id"])["version"]
    )
    project = review_project(
        project["id"], ReviewDecision.WITHDRAW.value, "programme descoped"
    )
    return alpha, project


def _submitted_filing_with_one_qualifying_project():
    """WMP-CYCLE for plan year 2026 with a single APPROVED project behind it, submitted to
    the regulator and awaiting both review tracks."""
    alpha = register_circuit(circuit_code="ALPHA")
    build_approved_project(
        alpha["id"],
        project_code="MP-CYCLE",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        unit_cost_per_mile_cents=1250000,
    )
    filing = open_filing(filing_code="WMP-CYCLE", plan_year=2026)
    return submit_filing(filing["id"])


# --------------------------------------------------------------------------
# Where the machines start
# --------------------------------------------------------------------------
def test_each_machine_entered_by_a_post_lands_on_its_declared_initial_state():
    """A work package, a notification batch, a resource center and a plan filing are each
    created in one call, and all four land on their own initial state with the counters that
    guard later transitions at zero.

    "A new project starts with `status` at `DRAFT`, `completed_miles` at zero,
    `review_round` at zero, and both `last_revision_reviewer_user_id` and `last_review_note`
    at null."

    "A planned batch starts with `status` at `PENDING`, `dispatched_at` and
    `lead_time_minutes` at null, and `target_count`, `delivered_count`, and
    `unreachable_count` all at zero."

    "A new site starts with `status` at `STANDBY` and with `psps_event_id`, `activated_at`,
    `demobilized_at`, `last_served_all_clear_at`, and `activation_order` all null."

    "A new filing starts at `DRAFT` with `safety_review_state` and `fiscal_review_state`
    both `PENDING`, `safety_reviewer_user_id` and `fiscal_reviewer_user_id` both null,
    `deficiency_round_count` at zero, and `last_deficiency_note` null."

    Design: Corner/state_machines/every_state_machine_lands_in_its_declared_initial_state
    """
    ctx = build_scoped_event()
    assert_circuit_state(
        read_circuit(ctx["charlie"]["id"]), energization_state="ENERGIZED"
    )

    project = get_success_data(
        api_client.create_mitigation_project(
            factories.mitigation_project_payload(
                ctx["charlie"]["id"],
                project_code="MP-INIT",
                program_type=ProgramType.COVERED_CONDUCTOR.value,
                planned_miles=1.0,
                unit_cost_per_mile_cents=1000000,
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert project["status"] == "DRAFT"
    assert_1dp(project["completed_miles"], 0.0)
    assert_integer(project["review_round"], 0)
    assert project["last_revision_reviewer_user_id"] is None
    assert project["last_review_note"] is None

    batch = get_success_data(
        api_client.create_notification_batch(
            factories.notification_batch_payload(
                ctx["event_id"],
                ADVANCE_24H_SEND_AT,
                stage=NotificationStage.ADVANCE_24H.value,
            ),
            LIAISON_HEADERS,
        ),
        201,
    )
    assert batch["status"] == "PENDING"
    assert batch["dispatched_at"] is None
    assert batch["lead_time_minutes"] is None
    assert_batch_outcome(
        batch, "PENDING", target_count=0, delivered_count=0, unreachable_count=0
    )

    center = get_success_data(
        api_client.create_resource_center(
            factories.resource_center_payload(
                resource_center_code="CRC-INIT", district_code="D-NORTH", site_capacity=100
            ),
            LIAISON_HEADERS,
        ),
        201,
    )
    assert center["accessibility_certified"] is False
    assert_center_state(
        center, "STANDBY", psps_event_id=None, last_served_all_clear_at=None
    )
    assert center["activated_at"] is None
    assert center["demobilized_at"] is None
    assert center["activation_order"] is None

    filing = get_success_data(
        api_client.create_plan_filing(
            factories.plan_filing_payload(filing_code="WMP-INIT", plan_year=2026),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert_filing_tracks(
        filing,
        status="DRAFT",
        safety_review_state="PENDING",
        fiscal_review_state="PENDING",
        safety_reviewer_user_id=None,
        fiscal_reviewer_user_id=None,
        deficiency_round_count=0,
    )
    assert filing["last_deficiency_note"] is None
    assert_versioned_entity(filing, expected_version=1)


# --------------------------------------------------------------------------
# EventScope: CONFIRMED -> EXCLUDED
# --------------------------------------------------------------------------
def test_excluding_a_scope_row_zeroes_its_term_and_rescores_the_event():
    """Holding CHARLIE out drops the event's avoided-ignition score by exactly CHARLIE's own
    4.30 and takes its five customers down to four, while the event stays scoped.

    "The row moves from `CONFIRMED` to `EXCLUDED` and its `ignition_risk_term` is set to
    0.00; a row that is already `EXCLUDED` yields `ERR_SCOPE_ALREADY_EXCLUDED`, and the
    operation is admitted only while the parent event's `scope_status` is `SCOPED` or
    `ARMED`, otherwise `ERR_EVENT_NOT_SCOPED`."

    "The event's counts, `ignition_risk_avoided_score`, and net-benefit figures are all
    recomputed under the `PRE_EVENT` variant, and both the scope row's `version` and the
    event's `version` increment by one each."

    Design: Corner/state_machines/event_scope_exclude_reverts_the_staged_circuit_and_rescores_the_event
    """
    ctx = build_scoped_event()
    rows = read_scope_rows(ctx["event_id"])
    assert_scope_row(rows, ctx["alpha"]["id"], ignition_risk_term=6.02)
    assert_scope_row(rows, ctx["bravo"]["id"], ignition_risk_term=5.16)
    charlie_row = assert_scope_row(
        rows, ctx["charlie"]["id"], ignition_risk_term=4.30, scope_status="CONFIRMED"
    )
    assert_2dp(ctx["event"]["ignition_risk_avoided_score"], 15.48)

    response = api_client.exclude_event_scope(
        charlie_row["id"],
        factories.exclude_payload(
            "distribution automation isolates the ignition-prone tap"
        ),
        ENGINEER_HEADERS,
    )

    excluded = get_success_data(response, 200)
    assert excluded["scope_status"] == "EXCLUDED"
    assert_2dp(excluded["ignition_risk_term"], 0.00)
    assert (
        excluded["exclusion_justification"]
        == "distribution automation isolates the ignition-prone tap"
    )
    assert excluded["version"] == charlie_row["version"] + 1

    event = read_event(ctx["event_id"])
    assert_event_dimensions(event, scope_status="SCOPED")
    assert_scope_counts(event, confirmed=2, excluded=1)
    assert_2dp(event["ignition_risk_avoided_score"], 11.18)
    assert_impact_counts(event, impacted=4, medical_baseline=1, critical_facility=1)
    assert event["benefit_variant"] == "PRE_EVENT"
    assert event["version"] == ctx["event"]["version"] + 1


def test_excluding_a_staged_circuit_takes_it_back_out_of_the_shutoff():
    """On an armed event the exclusion is a compensating action: CHARLIE returns to service
    with its posture recomputed, and the two circuits still confirmed stay staged.

    "When the circuit had already been staged for shutoff, the exclusion reverts it from
    `DE_ENERGIZATION_PENDING` back to `ENERGIZED` and recomputes its `risk_posture` out of
    `LOCKED` from its latest forecast index."

    "Arming then cascades onto every `CONFIRMED`-scoped circuit whose `energization_state`
    is `ENERGIZED`, moving each to `DE_ENERGIZATION_PENDING`, setting each circuit's
    `risk_posture` to `LOCKED`, and incrementing each circuit's `version` by one along with
    the event's own."

    Design: Corner/state_machines/event_scope_exclude_reverts_the_staged_circuit_and_rescores_the_event
    """
    ctx = build_armed_event()
    for key in ("alpha", "bravo", "charlie"):
        assert_circuit_state(
            read_circuit(ctx[key]["id"]),
            energization_state="DE_ENERGIZATION_PENDING",
            risk_posture="LOCKED",
        )
    charlie_row = scope_row_for(
        read_scope_rows(ctx["event_id"]), ctx["charlie"]["id"]
    )

    exclude_scope_row(charlie_row["id"], "switching plan isolates the tap")

    assert_circuit_state(
        read_circuit(ctx["charlie"]["id"]),
        energization_state="ENERGIZED",
        risk_posture="NORMAL",
    )
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="DE_ENERGIZATION_PENDING",
        risk_posture="LOCKED",
    )
    assert_circuit_state(
        read_circuit(ctx["bravo"]["id"]),
        energization_state="DE_ENERGIZATION_PENDING",
        risk_posture="LOCKED",
    )
    event = read_event(ctx["event_id"])
    assert_event_dimensions(event, scope_status="ARMED")
    assert_scope_counts(event, confirmed=2, excluded=1)
    assert_2dp(event["ignition_risk_avoided_score"], 11.18)


def test_a_second_exclusion_of_the_same_row_is_refused_and_subtracts_nothing():
    """EXCLUDED is the end of the road for a scope row, so the repeat call keeps the first
    justification and does not deduct CHARLIE's term twice.

    "The row moves from `CONFIRMED` to `EXCLUDED` and its `ignition_risk_term` is set to
    0.00; a row that is already `EXCLUDED` yields `ERR_SCOPE_ALREADY_EXCLUDED`, and the
    operation is admitted only while the parent event's `scope_status` is `SCOPED` or
    `ARMED`, otherwise `ERR_EVENT_NOT_SCOPED`."

    "Every `EXCLUDED` row carries `ignition_risk_term` pinned at 0.00 rather than being
    omitted from the set, which keeps the sum stable as circuits are held out."

    Design: Corner/state_machines/event_scope_exclude_twice_rejected
    """
    ctx = _scoped_chain_with_charlie_excluded()
    assert_2dp(read_event(ctx["event_id"])["ignition_risk_avoided_score"], 11.18)

    response = api_client.exclude_event_scope(
        ctx["charlie_scope"]["id"],
        factories.exclude_payload("second exclusion"),
        ENGINEER_HEADERS,
    )

    validate_error(response, ERR_SCOPE_ALREADY_EXCLUDED, 409)
    row = scope_row_for(read_scope_rows(ctx["event_id"]), ctx["charlie"]["id"])
    assert row["exclusion_justification"] == FIRST_EXCLUSION
    assert_2dp(row["ignition_risk_term"], 0.00)
    event = read_event(ctx["event_id"])
    assert_2dp(event["ignition_risk_avoided_score"], 11.18)
    assert_scope_counts(event, confirmed=2, excluded=1)


# --------------------------------------------------------------------------
# NotificationBatch: both exits are terminal
# --------------------------------------------------------------------------
def test_redispatching_a_partially_failed_batch_writes_no_second_record_set():
    """A batch that settled at FAILED_PARTIAL is finished, so the repeat dispatch is refused
    and the five records stay five.

    "Dispatch also re-checks that the event still has at least one `CONFIRMED` scope row,
    refusing with `ERR_NO_CIRCUITS_IN_SCOPE` otherwise, and refuses a batch whose `status`
    is already `DISPATCHED` or `FAILED_PARTIAL` with `ERR_BATCH_ALREADY_DISPATCHED`."

    "The batch settles at `DISPATCHED` when `unreachable_count` is zero and at
    `FAILED_PARTIAL` when it is greater than zero."

    Design: Corner/state_machines/notification_batch_dispatch_twice_rejected
    """
    ctx = build_advance_dispatched_event()
    assert_batch_outcome(
        ctx["batch_advance"],
        "FAILED_PARTIAL",
        target_count=5,
        delivered_count=4,
        unreachable_count=1,
    )

    response = api_client.dispatch_notification_batch(
        ctx["batch_advance"]["id"], LIAISON_HEADERS
    )

    validate_error(response, ERR_BATCH_ALREADY_DISPATCHED, 409)
    _, meta = read_records(notification_batch_id=ctx["batch_advance"]["id"])
    assert_integer(meta["total_count"], 5)
    assert_event_dimensions(
        read_event(ctx["event_id"]), notification_status="ADVANCE_SENT"
    )


def test_the_notification_dimension_walks_all_the_way_to_restoration_sent():
    """Four dispatches carry the communication dimension through its whole map, and the two
    post-onset stages settle on a lead time of exactly zero minutes.

    "Dispatching an `ADVANCE_48H` or `ADVANCE_24H` batch while the dimension reads
    `NOT_STARTED` advances it to `ADVANCE_SENT`; dispatching an `IMMINENT_1H` batch while it
    reads `ADVANCE_SENT` advances it to `IMMINENT_SENT`; dispatching an `ACTIVATION` batch
    while it reads `IMMINENT_SENT` advances it to `ACTIVATION_SENT`; and dispatching a
    `RESTORATION` batch while it reads `ACTIVATION_SENT` advances it to the terminal
    `RESTORATION_SENT`."

    "Each stage carries a minimum: `ADVANCE_48H` requires at least 48 hours of lead time,
    `ADVANCE_24H` at least 24 hours, `IMMINENT_1H` at least 60 minutes, and both
    `ACTIVATION` and `RESTORATION` require at least zero minutes, which is to say they may
    be sent right up to the onset instant but not after it."

    Design: Corner/state_machines/notification_status_advances_to_its_terminal_restoration_sent
    """
    ctx = build_imminent_dispatched_event()
    assert_event_dimensions(
        read_event(ctx["event_id"]), notification_status="IMMINENT_SENT"
    )

    activation = plan_batch(
        ctx["event_id"], NotificationStage.ACTIVATION.value, ONSET_AT
    )
    move_clock(ONSET_AT)
    activation = dispatch_batch(activation["id"])
    assert_integer(activation["lead_time_minutes"], 0)
    assert_batch_outcome(
        activation,
        "FAILED_PARTIAL",
        target_count=5,
        delivered_count=4,
        unreachable_count=1,
    )
    assert_event_dimensions(
        read_event(ctx["event_id"]), notification_status="ACTIVATION_SENT"
    )

    restoration = plan_batch(
        ctx["event_id"], NotificationStage.RESTORATION.value, ONSET_AT
    )
    restoration = dispatch_batch(restoration["id"])

    assert_integer(restoration["lead_time_minutes"], 0)
    assert_batch_outcome(
        restoration,
        "FAILED_PARTIAL",
        target_count=5,
        delivered_count=4,
        unreachable_count=1,
    )
    assert_event_dimensions(
        read_event(ctx["event_id"]), notification_status="RESTORATION_SENT"
    )
    _, meta = validate_paginated(
        api_client.list_event_notification_batches(ctx["event_id"], LIAISON_HEADERS)
    )
    assert_integer(meta["total_count"], 4)


# --------------------------------------------------------------------------
# PSPSEvent: terminal lockdown and the wrong-state refusals
# --------------------------------------------------------------------------
def test_a_closed_event_turns_away_every_further_transition_with_one_code():
    """Scope, arm, de-energize, all-clear and close all bounce off the same closed event
    with the terminal code, and none of them moves it.

    "Any state-advancing call against an event whose `scope_status` is already `CLOSED` or
    `CANCELLED` is rejected with `ERR_EVENT_TERMINAL` (409) at the own-state step,
    regardless of which specific transition was requested."

    "Closing moves the event to the terminal `CLOSED` status, freezes its `POST_EVENT`
    scores, demobilizes any resource center still `ACTIVATED` for the event, makes the event
    eligible for plan-filing metric roll-up, and increments the event's `version`."

    Design: Corner/state_machines/closed_event_rejects_every_further_transition
    """
    ctx = build_closed_event()
    closed_version = ctx["event"]["version"]
    assert_event_dimensions(ctx["event"], scope_status="CLOSED")

    validate_error(
        api_client.scope_psps_event(
            ctx["event_id"],
            factories.scope_payload(closed_version),
            OFFICER_HEADERS,
        ),
        ERR_EVENT_TERMINAL,
        409,
    )
    validate_error(
        api_client.arm_psps_event(ctx["event_id"], OFFICER_HEADERS),
        ERR_EVENT_TERMINAL,
        409,
    )
    validate_error(
        api_client.de_energize_psps_event(ctx["event_id"], OFFICER_HEADERS),
        ERR_EVENT_TERMINAL,
        409,
    )
    validate_error(
        api_client.all_clear_psps_event(ctx["event_id"], ANALYST_HEADERS),
        ERR_EVENT_TERMINAL,
        409,
    )
    validate_error(
        api_client.close_psps_event(ctx["event_id"], OFFICER_HEADERS),
        ERR_EVENT_TERMINAL,
        409,
    )

    untouched = read_event(ctx["event_id"])
    assert_event_dimensions(untouched, scope_status="CLOSED")
    assert_integer(untouched["version"], closed_version)
    assert_instant(untouched["actual_restored_at"], RESTORE_CHARLIE_AT)


def test_an_event_whose_breakers_are_open_can_no_longer_be_cancelled():
    """Once the shutoff is executing, cancellation is off the table and the refusal names
    that specifically rather than reporting a terminal state.

    "Cancellation is the compensating action, and it is available only before the breakers
    open: an event whose `scope_status` is `DRAFT`, `SCOPED`, or `ARMED` may be cancelled
    with a supplied `cancellation_reason`, while an event that is `ACTIVE`, `RESTORING`,
    `CLOSED`, or `CANCELLED` refuses the request with `ERR_EVENT_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_on_a_closed_event_is_not_cancellable
    """
    ctx = build_active_event()

    response = api_client.cancel_psps_event(
        ctx["event_id"],
        factories.cancel_payload("forecast collapsed"),
        OFFICER_HEADERS,
    )

    validate_error(response, ERR_EVENT_NOT_CANCELLABLE, 409)
    event = read_event(ctx["event_id"])
    assert_event_dimensions(event, scope_status="ACTIVE")
    assert event["cancellation_reason"] is None
    for key in ("alpha", "bravo", "charlie"):
        assert_circuit_state(
            read_circuit(ctx[key]["id"]), energization_state="DE_ENERGIZED"
        )


def test_the_all_clear_cannot_skip_the_arming_and_execution_edges():
    """Meteorology is the right actor and still cannot declare the window over on an event
    that never went dark; the refusal is about state, not about role.

    "An event that is not `ACTIVE` refuses the declaration with `ERR_EVENT_NOT_ACTIVE`."

    "The weather judgement is deliberately separated from the switching authority: only a
    `MeteorologyAnalyst` may declare the damaging-weather window over, advancing the event
    from `ACTIVE` to `RESTORING` and incrementing its `version`."

    Design: Corner/state_machines/all_clear_on_a_merely_scoped_event_rejected
    """
    ctx = build_scoped_event()

    response = api_client.all_clear_psps_event(ctx["event_id"], ANALYST_HEADERS)

    validate_error(response, ERR_EVENT_NOT_ACTIVE, 409)
    assert_event_dimensions(read_event(ctx["event_id"]), scope_status="SCOPED")


def test_arming_a_draft_event_fails_on_its_own_state_before_any_business_gate():
    """The event has no scope rows and no dispatched warning, yet the caller hears about the
    missing scope determination rather than the missing notification.

    "A `PSPSDutyOfficer` arms an event from `SCOPED` to `ARMED`, and three gates must clear
    first."

    "There must be an `ADVANCE_48H` batch for the event whose `status` is `DISPATCHED` or
    `FAILED_PARTIAL`, or the request is refused with `ERR_ADVANCE_NOTIFICATION_MISSING` — a
    partial delivery failure does **not** block arming, because the 48-hour warning has
    demonstrably gone out."

    Design: Corner/state_machines/arm_on_a_draft_event_reports_event_not_scoped
    """
    ctx = build_feeder_chain()
    draft = open_event(ctx["fpi_forecast"]["id"], event_code="EV-DRAFT")
    assert_event_dimensions(draft, scope_status="DRAFT")

    response = api_client.arm_psps_event(draft["id"], OFFICER_HEADERS)

    validate_error(response, ERR_EVENT_NOT_SCOPED, 409)
    still_draft = read_event(draft["id"])
    assert_event_dimensions(still_draft, scope_status="DRAFT")
    assert_scope_counts(still_draft, confirmed=0, excluded=0)


def test_a_rescope_replaces_the_previous_snapshot_rather_than_adding_to_it():
    """Re-running the determination after a manual exclusion rebuilds all three confirmed
    rows, restores the score and leaves the event with three rows, not six.

    "The call runs from `DRAFT` to `SCOPED` the first time and as a self-loop from `SCOPED`
    back to `SCOPED` on every re-scope after a forecast refresh; a re-scope first
    **hard-deletes** every existing scope row of the event and then rewrites the set from
    scratch, and it reverts any circuit that was staged for de-energization but is no longer
    confirmed back to `ENERGIZED`."

    "This is the only operation in the system that legitimately supersedes rows it did not
    itself create, which is precisely why it carries the version guard."

    Design: Corner/state_machines/rescope_replaces_the_previous_scope_snapshot_instead_of_appending
    """
    ctx = _scoped_chain_with_charlie_excluded()
    before = read_event(ctx["event_id"])
    assert_scope_counts(before, confirmed=2, excluded=1)
    assert_2dp(before["ignition_risk_avoided_score"], 11.18)

    rescoped = scope_event(ctx["event_id"], before["version"])

    assert_event_dimensions(rescoped, scope_status="SCOPED")
    assert_scope_counts(rescoped, confirmed=3, excluded=0)
    assert_2dp(rescoped["ignition_risk_avoided_score"], 15.48)
    assert_impact_counts(rescoped, impacted=5, medical_baseline=1, critical_facility=1)
    assert rescoped["version"] > before["version"]

    rows, meta = validate_paginated(
        api_client.list_event_scopes(ctx["event_id"], OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 3)
    assert len(rows) == 3
    for key in ("alpha", "bravo", "charlie"):
        assert_scope_row(rows, ctx[key]["id"], scope_status="CONFIRMED")
        assert_circuit_state(
            read_circuit(ctx[key]["id"]), energization_state="ENERGIZED"
        )


# --------------------------------------------------------------------------
# PatrolAssignment and the re-energization cascade
# --------------------------------------------------------------------------
def test_a_patrol_cannot_be_completed_before_it_has_been_started():
    """Completion is wired only from IN_PROGRESS, so the scheduled assignment keeps its
    empty stamps and the circuit is not nudged toward restoration.

    "Completing a patrol requires `miles_patrolled`, a value of at least zero, and moves the
    assignment from `IN_PROGRESS` to `COMPLETED`, stamping `completed_at` from the logical
    clock and recording the reported mileage; an assignment in any other status refuses the
    completion with `ERR_PATROL_INVALID_STATE`."

    "Completion drives the circuit from `PATROL_IN_PROGRESS` to `CLEARED_FOR_RESTORE`
    **unconditionally** — even when the patrol filed ignition-risk damage."

    Design: Corner/state_machines/patrol_complete_before_start_rejected
    """
    ctx = build_restoring_event()
    assignment = schedule_patrol(
        ctx["event_id"], ctx["alpha"]["id"], PATROL_START_AT, PATROL_DONE_AT
    )

    response = api_client.complete_patrol(
        assignment["id"], factories.complete_patrol_payload(7.0), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_PATROL_INVALID_STATE, 409)
    untouched = read_patrol(assignment["id"])
    assert untouched["status"] == "SCHEDULED"
    assert untouched["started_at"] is None
    assert untouched["completed_at"] is None
    assert_1dp(untouched["miles_patrolled"], 0.0)
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]), energization_state="DE_ENERGIZED"
    )


def test_re_energizing_aborts_only_the_unfinished_patrol_on_that_circuit():
    """ALPHA's leftover assignment is aborted while its completed sibling and the two
    assignments on the other circuits are left exactly as they were.

    "Finally, any patrol assignment still left on the circuit at `SCHEDULED` or
    `IN_PROGRESS` is moved to the terminal `ABORTED` status with its `version` incremented,
    because there is nothing left to patrol."

    "Then — and only when **every** `CONFIRMED` scope row of the event now carries a
    `restored_at` — the event's `actual_restored_at` is stamped, its `duration_hours` is
    recomputed, and its net-benefit figures are re-run under the `POST_EVENT` variant with
    `benefit_variant` set accordingly."

    Design: Corner/state_machines/re_energize_aborts_only_the_non_terminal_patrol_on_that_circuit
    """
    ctx = _restoring_chain_with_two_alpha_patrols()
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]), energization_state="CLEARED_FOR_RESTORE"
    )
    move_clock(RE_ENERGIZE_AT)

    response = api_client.re_energize_circuit(ctx["alpha"]["id"], OFFICER_HEADERS)

    get_success_data(response, 200)
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]), energization_state="ENERGIZED"
    )
    assert read_patrol(ctx["pa_alpha_2"]["id"])["status"] == "ABORTED"
    finished = read_patrol(ctx["pa_alpha"]["id"])
    assert finished["status"] == "COMPLETED"
    assert_1dp(finished["miles_patrolled"], 7.0)
    assert read_patrol(ctx["pa_bravo"]["id"])["status"] == "SCHEDULED"
    assert read_patrol(ctx["pa_charlie"]["id"])["status"] == "SCHEDULED"
    assert read_event(ctx["event_id"])["actual_restored_at"] is None

    _, meta = validate_paginated(
        api_client.list_patrol_assignments(
            SUPERVISOR_HEADERS,
            params={"circuit_id": ctx["alpha"]["id"], "status": "ABORTED"},
        )
    )
    assert_integer(meta["total_count"], 1)


# --------------------------------------------------------------------------
# MitigationProject
# --------------------------------------------------------------------------
def test_an_approved_package_cannot_be_submitted_again():
    """Submission is wired only out of DRAFT and REVISION_REQUESTED, so the approved package
    keeps its status and its already-computed figures.

    "A `GridPlanner` submits a project from either `DRAFT` or `REVISION_REQUESTED`,
    advancing it to `SUBMITTED`; submission from any other status is refused with
    `ERR_PROJECT_INVALID_STATE`, and submission is likewise refused with
    `ERR_CIRCUIT_POSTURE_LOCKED` when the circuit's posture has become `LOCKED` since
    booking."

    "Every submission recomputes `risk_reduction_score` against the circuit's *current*
    `hftd_tier`, so a terrain reclassification between rounds moves the score."

    Design: Corner/state_machines/project_submit_from_approved_rejected
    """
    alpha = register_circuit(circuit_code="ALPHA")
    project = build_approved_project(
        alpha["id"],
        project_code="MP-CC",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        unit_cost_per_mile_cents=1250000,
    )
    assert project["status"] == "APPROVED"

    response = api_client.submit_mitigation_project(project["id"], PLANNER_HEADERS)

    validate_error(response, ERR_PROJECT_INVALID_STATE, 409)
    unchanged = read_project(project["id"])
    assert unchanged["status"] == "APPROVED"
    assert_2dp(unchanged["risk_reduction_score"], 3.72)
    assert_integer(unchanged["budget_cents"], 5000000)


def test_a_withdrawn_package_refuses_both_the_reviewer_and_the_inspector():
    """From the terminal status neither a second withdrawal nor a further completion record
    is admitted, and the reversed ledger is not touched again.

    "A `RegulatoryReviewer` may withdraw a project whose `status` is `IN_EXECUTION`,
    `SUSPENDED`, or `COMPLETED`; from any other status the decision is refused with
    `ERR_PROJECT_INVALID_STATE`, and no decision of any kind is admitted once a project is
    `WITHDRAWN`."

    "Each record adds `completed_miles_delta` to the project's `completed_miles`; the call
    is refused with `ERR_MITIGATION_MILES_EXCEEDED` when the resulting cumulative total
    would exceed `planned_miles`, and with `ERR_PROJECT_INVALID_STATE` when the project's
    `status` is neither `APPROVED` nor `IN_EXECUTION`."

    Design: Corner/state_machines/withdrawn_project_rejects_further_review_and_completion
    """
    alpha, project = _withdrawn_covered_conductor_project()
    assert project["status"] == "WITHDRAWN"
    circuit_version = read_circuit(alpha["id"])["version"]

    second_withdrawal = api_client.review_mitigation_project(
        project["id"],
        factories.project_review_payload(ReviewDecision.WITHDRAW.value),
        REVIEWER_HEADERS,
    )
    validate_error(second_withdrawal, ERR_PROJECT_INVALID_STATE, 409)

    further_completion = api_client.record_project_completion(
        project["id"],
        factories.record_completion_payload(
            1.0, "2026-07-15T00:00:00Z", circuit_version
        ),
        INSPECTOR_HEADERS,
    )
    validate_error(further_completion, ERR_PROJECT_INVALID_STATE, 409)

    unchanged = read_project(project["id"])
    assert unchanged["status"] == "WITHDRAWN"
    assert_1dp(unchanged["completed_miles"], 0.0)
    restored = read_circuit(alpha["id"])
    assert_hardening_ledger(
        restored,
        covered_conductor_miles=0.0,
        underground_miles=0.0,
        hardened_fraction=0.0000,
    )
    assert_integer(restored["version"], circuit_version)


# --------------------------------------------------------------------------
# WildfirePlanFiling: the bounded cure loop and the latching fork legs
# --------------------------------------------------------------------------
def test_the_third_deficiency_ends_the_cure_loop_in_the_terminal_rejection():
    """Two deficiencies issue cure rounds that re-submission does not reset, and the third
    goes straight to the terminal rejection with the counter at three.

    "While `deficiency_round_count` was below 2 before the decision, the filing moves to
    `DEFICIENCY_ISSUED`, from which a cure round can re-submit it."

    "When `deficiency_round_count` was already exactly 2, the third deficiency is fatal: the
    filing moves to the terminal `REJECTED` status with `deficiency_round_count` set to 3."

    "What submission does **not** reset is `deficiency_round_count`, which accumulates
    across the whole life of the filing and is what eventually exhausts the regulator's
    patience."

    Design: Corner/state_machines/filing_third_deficient_round_terminates_the_cycle_in_rejected
    """
    filing = _submitted_filing_with_one_qualifying_project()
    assert_filing_metrics(filing, qualifying_project_count=1)

    first = review_filing(
        filing["id"],
        ReviewTrack.SAFETY.value,
        FilingDecision.DEFICIENT.value,
        ROUND_ONE_NOTE,
    )
    assert_filing_tracks(
        first,
        status="DEFICIENCY_ISSUED",
        safety_review_state="DEFICIENT",
        deficiency_round_count=1,
    )
    assert first["last_deficiency_note"] == ROUND_ONE_NOTE

    cured = submit_filing(filing["id"])
    assert_filing_tracks(
        cured,
        status="SUBMITTED",
        safety_review_state="PENDING",
        fiscal_review_state="PENDING",
        deficiency_round_count=1,
    )

    second = review_filing(
        filing["id"],
        ReviewTrack.SAFETY.value,
        FilingDecision.DEFICIENT.value,
        ROUND_TWO_NOTE,
    )
    assert_filing_tracks(
        second, status="DEFICIENCY_ISSUED", deficiency_round_count=2
    )

    submit_filing(filing["id"])
    third = review_filing(
        filing["id"],
        ReviewTrack.FISCAL.value,
        FilingDecision.DEFICIENT.value,
        ROUND_THREE_NOTE,
        headers=REVIEWER_2_HEADERS,
    )
    assert_filing_tracks(
        third,
        status="REJECTED",
        safety_review_state="PENDING",
        fiscal_review_state="DEFICIENT",
        deficiency_round_count=3,
    )
    assert third["last_deficiency_note"] == ROUND_THREE_NOTE

    response = api_client.submit_plan_filing(filing["id"], PLANNER_HEADERS)

    validate_error(response, ERR_FILING_INVALID_STATE, 409)
    assert_filing_tracks(read_filing(filing["id"]), status="REJECTED")


def test_a_cleared_review_track_cannot_be_flipped_by_a_second_decision():
    """The two fork legs latch individually, so the cleared safety track refuses a change of
    mind while the fiscal leg is still waiting.

    "A decision is admitted only while the filing's `status` is `SUBMITTED`, otherwise
    `ERR_FILING_INVALID_STATE`, and only while the named track's own state is still
    `PENDING`; a track already `CLEARED` or `DEFICIENT` in the current round refuses the
    decision with `ERR_REVIEW_TRACK_ALREADY_DECIDED`."

    "A `CLEAR` decision on the **first** of the two tracks sets that track's state to
    `CLEARED` and its reviewer identifier to the acting `X-User-ID`, and leaves the filing
    at `SUBMITTED` waiting for its sibling — one leg of the join has landed."

    Design: Corner/state_machines/filing_review_on_an_already_decided_track_rejected
    """
    filing = _submitted_filing_with_one_qualifying_project()
    cleared = review_filing(
        filing["id"],
        ReviewTrack.SAFETY.value,
        FilingDecision.CLEAR.value,
        headers=REVIEWER_HEADERS,
    )
    assert_filing_tracks(
        cleared,
        status="SUBMITTED",
        safety_review_state="CLEARED",
        fiscal_review_state="PENDING",
        safety_reviewer_user_id=REVIEWER_ALPHA,
        fiscal_reviewer_user_id=None,
        deficiency_round_count=0,
    )
    version_after_clear = cleared["version"]

    response = api_client.review_plan_filing(
        filing["id"],
        factories.filing_review_payload(
            ReviewTrack.SAFETY.value,
            FilingDecision.DEFICIENT.value,
            "changed my mind",
        ),
        REVIEWER_HEADERS,
    )

    validate_error(response, ERR_REVIEW_TRACK_ALREADY_DECIDED, 409)
    unchanged = read_filing(filing["id"])
    assert_filing_tracks(
        unchanged,
        status="SUBMITTED",
        safety_review_state="CLEARED",
        fiscal_review_state="PENDING",
        deficiency_round_count=0,
    )
    assert unchanged["last_deficiency_note"] is None
    assert_integer(unchanged["version"], version_after_clear)
    assert unchanged["fiscal_reviewer_user_id"] is None
    assert unchanged["safety_reviewer_user_id"] == REVIEWER_ALPHA
