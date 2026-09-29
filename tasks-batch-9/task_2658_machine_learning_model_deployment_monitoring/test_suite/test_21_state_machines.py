"""Where each ladder starts, how it loops, and where it stops for good."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    assert_allocated_traffic,
    assert_dataset_state,
    assert_deployment_state,
    assert_pct,
    assert_ramp_step_row,
    assert_sweep_counters,
    assert_version_state,
)
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_TERMINAL_STATE,
)
from test_helpers.factories import (
    build_dataset_decision_payload,
    build_incident_action_payload,
    build_revalidation_disposition_payload,
    build_rollout_action_payload,
)
from test_helpers.fixtures import (
    build_stack,
    create_draft_dataset,
    create_incident,
    incident_action,
    ledger_rows,
    ramp,
    rollout,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_1,
    APPROVER_2,
    MLE_1,
    RELIABILITY_1,
    STEWARD_1,
    USER_APPR_2,
    USER_MLE_1,
    USER_STEW_1,
)

# ─── Four machines, four initial states ───


def test_every_new_row_lands_on_its_own_declared_initial_state(api):
    """The two dimensions of one deployment row start independently.

    PRD 3.2 starts a snapshot's `approval_state` "at `DRAFT`"; PRD 3.3 spans the
    version ladder "`DRAFT`, `PENDING_REVIEW`, ..." from DRAFT; PRD 3.4 starts a
    cluster with "`operational_state` of `OPEN`" and a deployment with
    "`rollout_state` of `PENDING`, `health_state` of `HEALTHY`, `traffic_pct` of
    0.00, `ramp_step_index` of 0, `cumulative_ramp_delta_pct` of 0.00,
    `manual_override_active` false", its `target_traffic_pct` "set to the final
    checkpoint of its pattern's ramp table, which is 100.00 for every pattern",
    while "a `PENDING` deployment contributes 0.00" to the cluster's ledger.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    fresh_snapshot = create_draft_dataset(api)
    assert_dataset_state(fresh_snapshot, approval_state="DRAFT")

    stack = build_stack(api)
    assert_version_state(
        stack.version, approval_state="APPROVED", blocked_reason=None
    )
    assert stack.endpoint["operational_state"] == "OPEN"

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        deployment,
        rollout_state="PENDING",
        health_state="HEALTHY",
        traffic_pct=0.00,
        ramp_step_index=0,
        cumulative_ramp_delta_pct=0.00,
        manual_override_active=False,
    )
    assert_pct(deployment["target_traffic_pct"], 100.00, "target_traffic_pct")
    assert deployment["override_traffic_pct"] is None
    assert deployment["health_score_provisional"] is None
    assert deployment["health_score_final"] is None
    assert deployment["rolled_back_at"] is None

    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 0.00)

    _, ledger_meta = validate_paginated(
        api.list_traffic_ramp_steps(
            RELIABILITY_1, {"deployment_id": stack.deployment_id}
        )
    )
    assert ledger_meta["total_count"] == 0


# ─── The pause pair, which moves state and nothing else ───


def test_hold_and_resume_preserve_the_checkpoint_the_ramp_reached(api):
    """The pause pair writes no traffic, no index and no ledger row.

    PRD 3.4: HOLD "moves `RAMPING → HELD` and does nothing else: `traffic_pct` and
    `ramp_step_index` are left exactly as they were, so the cluster's
    `allocated_traffic_pct` does not change either — `HELD` is inside the ledger's
    contributing state set. No ledger row is appended." RESUME "moves
    `HELD → RAMPING` with `traffic_pct` unchanged", and the checkpoint table then
    resumes from the preserved index rather than restarting.

    Design: Corner/state_machines/hold_then_resume_preserves_traffic_pct_and_ramp_step_index
    """
    stack = build_stack(api, ramps=2)

    held = rollout(api, stack.deployment_id, "HOLD")
    assert_deployment_state(
        held,
        rollout_state="HELD",
        health_state="HEALTHY",
        traffic_pct=15.00,
        ramp_step_index=2,
    )
    endpoint_while_held = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint_while_held, 15.00)

    resumed = rollout(api, stack.deployment_id, "RESUME")
    assert_deployment_state(
        resumed,
        rollout_state="RAMPING",
        health_state="HEALTHY",
        traffic_pct=15.00,
        ramp_step_index=2,
    )

    stepped = ramp(api, stack.deployment_id)
    assert_deployment_state(
        stepped,
        rollout_state="RAMPING",
        health_state="HEALTHY",
        traffic_pct=35.00,
        ramp_step_index=3,
    )

    rows = ledger_rows(api, stack.deployment_id)
    assert len(rows) == 3, "the pause pair appends no ledger row"
    assert_ramp_step_row(rows[-1], step_index=2, delta_pct=20.00, reason="RAMP_STEP")


# ─── A trigger replayed from the state it already reached ───


def test_replaying_the_submit_trigger_from_submitted_is_refused(api):
    """Submit is not idempotent, and the refusal writes nothing.

    PRD 3.2 declares the submit transition as taking a snapshot "from `DRAFT` to
    `SUBMITTED`" and the resubmission loop only "when it is invoked on a snapshot
    whose `approval_state` is `REJECTED`", so SUBMITTED is not an accepted
    from-state and PRD 2.7 answers ERR_INVALID_STATE at HTTP 409. A request
    that stops in the state band never reaches the write, so the concurrency token
    does not move either.

    Design: Corner/state_machines/submitting_an_already_submitted_dataset_is_rejected_as_invalid_state
    """
    dataset = create_draft_dataset(api)
    submitted = get_success_data(api.submit_training_dataset(dataset["id"], MLE_1))
    assert_dataset_state(submitted, approval_state="SUBMITTED")
    assert submitted["version"] == 2

    replayed = api.submit_training_dataset(dataset["id"], MLE_1)
    validate_error(replayed, ERR_INVALID_STATE, 409)

    after = get_success_data(api.get_training_dataset(dataset["id"], STEWARD_1))
    assert_dataset_state(after, approval_state="SUBMITTED")
    assert after["version"] == 2
    assert after["decided_by_user_id"] is None
    assert after["decided_at"] is None


# ─── A terminal state that answers a different code from a wrong state ───


def test_a_retired_deployment_answers_terminal_state_to_everything(api):
    """The terminal check outranks the ordinary wrong-from-state check.

    PRD 3.4 makes RETIRE "accepted from `PENDING`, `LIVE` or `DRAINING`", puts
    `ROLLED_BACK` and `RETIRED` among the terminal rollout states, and appends "no
    ledger row at all when `traffic_pct` was already 0.00" while a retired
    deployment's allocation is "fully released" because RETIRED "sits **outside**
    the contributing state set". PRD 2.7 orders "ERR_TERMINAL_STATE before
    ERR_INVALID_STATE" inside the state band.

    Design: Corner/state_machines/retired_deployment_rejects_every_further_action_with_terminal_state
    """
    stack = build_stack(api)

    retired = rollout(api, stack.deployment_id, "RETIRE")
    assert_deployment_state(retired, rollout_state="RETIRED", traffic_pct=0.00)
    assert ledger_rows(api, stack.deployment_id) == []

    validate_error(
        api.ramp_deployment(stack.deployment_id, RELIABILITY_1),
        ERR_TERMINAL_STATE,
        409,
    )
    validate_error(
        api.rollout_action(
            stack.deployment_id,
            build_rollout_action_payload("HOLD"),
            RELIABILITY_1,
        ),
        ERR_TERMINAL_STATE,
        409,
    )
    validate_error(
        api.rollout_action(
            stack.deployment_id,
            build_rollout_action_payload("RETIRE"),
            RELIABILITY_1,
        ),
        ERR_TERMINAL_STATE,
        409,
    )

    unmoved = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(unmoved, rollout_state="RETIRED", traffic_pct=0.00)
    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 0.00)


# ─── An unbounded loop that clears its previous decision on every pass ───


def test_a_rejected_snapshot_loops_back_through_draft_on_resubmission(api):
    """The loop passes through DRAFT and clears the recorded decision.

    PRD 3.2: invoked on a REJECTED snapshot, "the row first returns
    `REJECTED → DRAFT` — clearing `decided_by_user_id` and `decided_at` back to
    null — and then, in the very same request, the `DRAFT → SUBMITTED` transition
    is applied. A single call therefore lands on `SUBMITTED` with a cleared decision
    record." Nothing on the snapshot counts attempts, so the loop may run again.

    Design: Corner/state_machines/rejected_dataset_resubmission_loops_back_through_draft
    """
    dataset = create_draft_dataset(api)
    get_success_data(api.submit_training_dataset(dataset["id"], MLE_1))

    rejected = get_success_data(
        api.decide_training_dataset(
            dataset["id"],
            build_dataset_decision_payload("REJECT", note="row count below the floor"),
            STEWARD_1,
        )
    )
    assert_dataset_state(rejected, approval_state="REJECTED")
    assert rejected["decided_by_user_id"] == USER_STEW_1
    assert rejected["decided_at"] == "2026-08-01T00:00:00Z"

    looped = get_success_data(api.submit_training_dataset(dataset["id"], MLE_1))
    assert_dataset_state(looped, approval_state="SUBMITTED")
    assert looped["decided_by_user_id"] is None
    assert looped["decided_at"] is None

    rejected_again = get_success_data(
        api.decide_training_dataset(
            dataset["id"], build_dataset_decision_payload("REJECT"), STEWARD_1
        )
    )
    assert_dataset_state(rejected_again, approval_state="REJECTED")

    looped_again = get_success_data(api.submit_training_dataset(dataset["id"], MLE_1))
    assert_dataset_state(looped_again, approval_state="SUBMITTED")
    assert looped_again["decided_by_user_id"] is None

    approved = get_success_data(
        api.decide_training_dataset(
            dataset["id"], build_dataset_decision_payload("APPROVE"), STEWARD_1
        )
    )
    assert_dataset_state(approved, approval_state="APPROVED")
    assert approved["decided_by_user_id"] == USER_STEW_1

    rows, meta = validate_paginated(api.list_training_datasets(MLE_1))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == dataset["id"]
    assert rows[0]["registered_by_user_id"] == USER_MLE_1


# ─── A recurrence loop bounded by a counter rather than by a payload ───


def test_the_second_recurrence_escalates_and_resolve_closes_the_incident(api):
    """One trigger, two destinations, chosen by the incremented count.

    PRD 3.8: ENGAGE_FALLBACK sets "`fallback_engaged` ... true and
    `fallback_strategy_used` captures the deployment's `fallback_strategy`", moving
    no traffic; RECUR forks because "the comparison is made against the
    **incremented** count", so "when `recurrence_count` plus 1 is strictly below 2
    the incident moves `MONITORING → MITIGATING`" and otherwise it "moves
    `MONITORING → ESCALATED` and `severity` is forcibly raised to `SEV1`"; RESOLVE
    "stamps `resolved_at` from the logical clock" and "an incident that never
    applied an override releases nothing and touches no traffic".

    Design: Corner/state_machines/incident_recurrence_escalates_at_the_max_and_resolve_stamps_closure
    """
    stack = build_stack(api, ramps=1)
    incident = create_incident(api, stack.deployment_id)
    assert incident["status"] == "OPEN"
    assert incident["model_version_id"] == stack.version_id
    assert incident["drift_report_id"] is None
    assert incident["source"] == "MANUAL"
    assert incident["severity"] == "SEV3"
    assert incident["recurrence_count"] == 0
    assert incident["fallback_engaged"] is False
    assert incident["opened_at"] == "2026-08-01T00:00:00Z"

    mitigating = incident_action(api, incident["id"], "ENGAGE_FALLBACK")
    assert mitigating["status"] == "MITIGATING"
    assert mitigating["fallback_engaged"] is True
    assert mitigating["fallback_strategy_used"] == "PREVIOUS_CHAMPION"
    assert mitigating["manual_override_traffic_pct"] is None
    untouched = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        untouched, traffic_pct=5.00, manual_override_active=False
    )

    assert incident_action(api, incident["id"], "MONITOR")["status"] == "MONITORING"

    first_recurrence = incident_action(api, incident["id"], "RECUR")
    assert first_recurrence["status"] == "MITIGATING"
    assert first_recurrence["recurrence_count"] == 1
    assert first_recurrence["severity"] == "SEV3"

    assert incident_action(api, incident["id"], "MONITOR")["status"] == "MONITORING"

    second_recurrence = incident_action(api, incident["id"], "RECUR")
    assert second_recurrence["status"] == "ESCALATED"
    assert second_recurrence["recurrence_count"] == 2
    assert second_recurrence["severity"] == "SEV1"

    set_clock(api, "2026-08-02T00:00:00Z")
    resolved = incident_action(api, incident["id"], "RESOLVE")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] == "2026-08-02T00:00:00Z"
    assert resolved["recurrence_count"] == 2

    after = get_success_data(api.get_deployment(stack.deployment_id, RELIABILITY_1))
    assert_deployment_state(after, traffic_pct=5.00, health_state="HEALTHY")

    replayed = api.incident_action(
        incident["id"], build_incident_action_payload("MONITOR"), RELIABILITY_1
    )
    validate_error(replayed, ERR_TERMINAL_STATE, 409)


# ─── A cascade whose fourth hop is a no-op because nothing qualifies ───


def test_a_failed_revalidation_blocks_the_version_and_drains_its_traffic(api):
    """Three hops land inside the one disposition request; the fourth finds nothing.

    PRD 3.9: FAIL "moves `IN_REVIEW → FAILED`", then hop 2 takes the version
    "from `APPROVED` to `BLOCKED`, writes `blocked_reason` of `REVALIDATION_FAILED`,
    and clears `revalidation_due_at` to null", then hop 3 takes each serving
    deployment "into `DRAINING`, sets `traffic_pct` to 0.00, appends one ramp-ledger
    row whose `reason` is `DRAIN_RELEASE` and whose `delta_pct` is the negative of
    the traffic the deployment held immediately before, and recomputes the owning
    serving cluster's `allocated_traffic_pct`". Hop 4 acts only on COLLECTING
    evaluations, of which there are none.

    Design: Corner/state_machines/revalidation_failure_cascades_down_to_version_and_deployment
    """
    stack = build_stack(api, ramps=2)
    assert_version_state(stack.version, revalidation_due_at="2026-10-30T00:00:00Z")

    set_clock(api, "2026-10-31T00:00:00Z")
    sweep = get_success_data(api.run_revalidation_sweep(ADMIN_1))
    assert_sweep_counters(sweep, evaluated_count=1, created_count=1)

    tasks, task_meta = validate_paginated(
        api.list_revalidation_tasks(APPROVER_2, {"model_version_id": stack.version_id})
    )
    assert task_meta["total_count"] == 1
    task = tasks[0]
    assert task["status"] == "DUE"
    assert task["due_at"] == "2026-10-30T00:00:00Z"
    assert task["swept_at"] == "2026-10-31T00:00:00Z"

    in_review = get_success_data(
        api.disposition_revalidation_task(
            task["id"],
            build_revalidation_disposition_payload("START_REVIEW"),
            APPROVER_2,
        )
    )
    assert in_review["status"] == "IN_REVIEW"
    assert in_review["reviewer_user_id"] == USER_APPR_2

    failed = get_success_data(
        api.disposition_revalidation_task(
            task["id"],
            build_revalidation_disposition_payload(
                "FAIL", findings="calibration drifted outside the approved envelope"
            ),
            APPROVER_2,
        )
    )
    assert failed["status"] == "FAILED"
    assert failed["decided_at"] == "2026-10-31T00:00:00Z"
    assert failed["findings"] == "calibration drifted outside the approved envelope"

    version = get_success_data(api.get_model_version(stack.version_id, APPROVER_2))
    assert_version_state(
        version,
        approval_state="BLOCKED",
        blocked_reason="REVALIDATION_FAILED",
        revalidation_due_at=None,
    )

    deployment = get_success_data(
        api.get_deployment(stack.deployment_id, RELIABILITY_1)
    )
    assert_deployment_state(
        deployment, rollout_state="DRAINING", traffic_pct=0.00
    )
    endpoint = get_success_data(
        api.get_serving_endpoint(stack.endpoint_id, RELIABILITY_1)
    )
    assert_allocated_traffic(endpoint, 0.00)

    drains = ledger_rows(api, stack.deployment_id, "DRAIN_RELEASE")
    assert len(drains) == 1
    assert_ramp_step_row(
        drains[0], delta_pct=-15.00, to_traffic_pct=0.00, reason="DRAIN_RELEASE"
    )

    _, evaluation_meta = validate_paginated(
        api.list_challenger_evaluations(
            RELIABILITY_1, {"challenger_deployment_id": stack.deployment_id}
        )
    )
    assert evaluation_meta["total_count"] == 0
