"""Initial states, declared transitions, unmet preconditions and terminal lockdown."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    assert_axes,
    assert_common_fields,
    assert_instant,
    assert_posture,
    assert_reserved_capacity,
    assert_runbook_state,
    assert_step_validation,
    factories as f,
    fixtures as fx,
)


def test_a_new_exercise_sits_at_the_initial_value_of_all_three_axes(api):
    """Creation leaves every axis, every score and every measurement at its start.

    PRD: "A new exercise starts all three of its lifecycle axes at their initial
    values — `execution_state` `DRAFT`, `data_state` `DATA_NOT_STARTED`,
    `failback_state` `FAILBACK_NOT_PLANNED` — with `required_capacity_units` at 0
    and every score, objective, measurement and approval field null."

    Design: Corner/state_machines/new_exercise_starts_draft_on_all_three_axes
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_SITES_REGISTERED
    )
    coordinator = estate["coordinator_headers"]

    exercise = validate_success(
        api.create_exercise(
            f.exercise_payload(
                recovery_site_id=estate["site_recovery"]["id"],
                coordinator_id=estate["coordinator"]["id"],
                planned_start_at="2026-08-20T00:00:00Z",
                planned_end_at="2026-08-20T06:00:00Z",
                name="Fresh exercise",
            ),
            coordinator,
        ),
        201,
    )

    assert_axes(
        exercise,
        execution_state="DRAFT",
        data_state="DATA_NOT_STARTED",
        failback_state="FAILBACK_NOT_PLANNED",
        closure_reason="NONE",
    )
    assert exercise["required_capacity_units"] == 0
    for field in (
        "provisional_impact_score",
        "production_impact_score",
        "required_approval_level",
        "impact_approved_by_id",
        "rto_objective_minutes",
        "rpo_objective_minutes",
        "achieved_rto_minutes",
        "achieved_rpo_minutes",
        "rto_met",
        "rpo_met",
        "execution_started_at",
        "failover_completed_at",
    ):
        assert exercise[field] is None, f"{field} should start null"
    assert_common_fields(exercise, expected_version=1)
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 0
    )


def test_submitting_a_runbook_with_one_pending_step_scores_zero(api):
    """The pending step counts in the total weight yet contributes nothing.

    PRD: "Start by summing the `weight` of every step of the runbook — every step,
    whatever its `validation_status`, including `PENDING` and `INVALIDATED` ones —
    to get the total weight." And: "A step in any other status — `PENDING` or
    `INVALIDATED` — scores 0.00 outright."

    Design: Corner/state_machines/submit_runbook_holding_one_step_moves_draft_to_in_review
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_STEP_ADDED)
    coordinator = estate["coordinator_headers"]

    runbook = fx.transition_runbook(
        api, coordinator, estate["runbook"]["id"], "SUBMIT_FOR_REVIEW"
    )

    assert_runbook_state(runbook, "IN_REVIEW", readiness_score=0.00)
    assert runbook["validated_at"] is None
    step = fx.read_step(api, coordinator, estate["step_core"]["id"])
    assert_step_validation(step, "PENDING")
    assert step["last_validated_at"] is None
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert_posture(group, "RESTRICTED", "NO_VALIDATED_RUNBOOK")
    assert group["current_runbook_id"] is None


def test_submitting_a_stepless_runbook_is_refused(api):
    """The review precondition is a step, so an empty revision cannot advance.

    PRD: "`SUBMIT_FOR_REVIEW` moves a runbook from `DRAFT` to `IN_REVIEW` and
    requires at least one step to exist." And: "Any action attempted from a status
    that does not declare it, or with its precondition unmet, is rejected with
    `ERR_INVALID_RUNBOOK_STATE`."

    Design: Corner/state_machines/submit_runbook_with_no_steps_rejected
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_RUNBOOK_OPENED)
    coordinator = estate["coordinator_headers"]
    runbook_id = estate["runbook"]["id"]

    validate_error(
        api.transition_runbook(
            runbook_id, f.runbook_transition_payload("SUBMIT_FOR_REVIEW"), coordinator
        ),
        ApiErrorId.ERR_INVALID_RUNBOOK_STATE,
        409,
    )

    assert_runbook_state(
        fx.read_runbook(api, coordinator, runbook_id), "DRAFT", readiness_score=0.00
    )
    _, meta = validate_paginated(
        api.list_runbook_steps(coordinator, params={"runbook_id": runbook_id})
    )
    assert meta["total_count"] == 0


def test_each_axis_reports_its_own_invalid_state_error_from_scheduled(api):
    """The three axes are refused separately and none of them moves.

    PRD: "An action attempted from a `data_state` that does not declare it, or
    while `execution_state` is anything other than `FAILOVER_COMPLETE`, is
    rejected with `ERR_INVALID_DATA_STATE`." And: "An action attempted from a
    `failback_state` that does not declare it, or while `execution_state` is
    anything other than `FAILOVER_COMPLETE`, is rejected with
    `ERR_INVALID_FAILBACK_STATE`." And: "Any execution action attempted from a
    state that does not declare it is rejected with `ERR_INVALID_EXERCISE_STATE`."

    Design: Corner/state_machines/axis_actions_from_scheduled_return_their_own_invalid_state_errors
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    operator = estate["operator_headers"]
    exercise = fx.setup_scheduled_exercise(
        api,
        estate,
        name="Scheduled but not started",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    validate_error(
        api.transition_execution(
            exercise["id"],
            f.execution_transition_payload("COMPLETE_FAILOVER"),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_EXERCISE_STATE,
        409,
    )
    validate_error(
        api.transition_data(
            exercise["id"], f.axis_transition_payload("BEGIN_VALIDATION"), operator
        ),
        ApiErrorId.ERR_INVALID_DATA_STATE,
        409,
    )
    validate_error(
        api.transition_failback(
            exercise["id"], f.axis_transition_payload("PLAN"), operator
        ),
        ApiErrorId.ERR_INVALID_FAILBACK_STATE,
        409,
    )

    assert_axes(
        fx.read_exercise(api, coordinator, exercise["id"]),
        execution_state="SCHEDULED",
        data_state="DATA_NOT_STARTED",
        failback_state="FAILBACK_NOT_PLANNED",
    )
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 2
    )


def test_a_sealed_evidence_package_refuses_every_further_action(api):
    """Sealing stamps the instant and locks the package against reopening.

    PRD: "`SEAL`, back in the hands of the `AuditLiaison`, moves `SIGNED_OFF` to
    the terminal `SEALED` and stamps `sealed_at` with the current logical clock."
    And: "A sealed package is tamper-evident and immutable: any further transition
    on it, whatever the action, is rejected with `ERR_EVIDENCE_SEALED`, and that
    seal check is evaluated before any of the segregation or business checks."

    Design: Corner/state_machines/sealed_evidence_package_rejects_every_further_transition
    """
    estate = fx.setup_evidence_scenario(api)
    coordinator = estate["coordinator_headers"]
    liaison = estate["liaison_headers"]
    package_id = estate["package"]["id"]
    fx.drive_both_axes_to_terminal(
        api, estate["operator_headers"], estate["exercise"]["id"]
    )
    fx.drive_execution(api, coordinator, estate["exercise"]["id"], "CLOSE")
    fx.transition_evidence(api, liaison, package_id, "SUBMIT")
    fx.transition_evidence(
        api,
        estate["approver_headers"],
        package_id,
        "SIGN_OFF",
        note="Reviewed against the exercise record",
    )

    sealed = fx.transition_evidence(api, liaison, package_id, "SEAL")

    assert sealed["state"] == "SEALED"
    assert_instant(sealed["sealed_at"], CLOCK_EPOCH)
    assert sealed["signed_off_by_id"] == estate["risk_approver"]["id"]
    assert sealed["manifest_line_count"] == 3
    validate_error(
        api.transition_evidence_package(
            package_id,
            f.evidence_transition_payload("RETURN", "Trying to reopen a sealed package"),
            liaison,
        ),
        ApiErrorId.ERR_EVIDENCE_SEALED,
        409,
    )
    still_sealed = fx.read_evidence_package(api, liaison, package_id)
    assert still_sealed["state"] == "SEALED"
    assert still_sealed["return_reason"] == "NONE"


def test_agreeing_a_tier_twice_is_refused(api):
    """The decision endpoint is declared only from the proposed state.

    PRD: "Only the application's own business owner may decide the proposal, and
    only while the application sits in `TIER_PROPOSED`; a decision attempted from
    any other tier state is rejected with `ERR_INVALID_APPLICATION_TIER_STATE`."

    Design: Corner/state_machines/second_agree_on_the_same_application_rejected
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_APPLICATION_AGREED
    )
    application_id = estate["app_core"]["id"]

    validate_error(
        api.decide_application_tier(
            application_id,
            f.tier_decision_payload("AGREE", "Agreeing a second time"),
            estate["owner_headers"],
        ),
        ApiErrorId.ERR_INVALID_APPLICATION_TIER_STATE,
        409,
    )

    application = validate_success(
        api.get_application(application_id, estate["coordinator_headers"])
    )
    assert application["tier_agreement_status"] == "AGREED"
    assert application["tier"] == "TIER_1"
    assert application["rto_minutes"] == 60
    assert application["rpo_minutes"] == 15
    assert application["retier_count"] == 0


def test_validating_a_second_revision_supersedes_the_first(api):
    """The later revision becomes operative and the earlier one is superseded.

    PRD: "On reaching `VALIDATED`, the server stamps `validated_at` with the
    current logical clock, resets `stale_reason` to `NONE`, recomputes
    `readiness_score`, re-points the owning group's `current_runbook_id` at this
    revision, marks any earlier revision of the same group `SUPERSEDED` with
    `stale_reason` `SUPERSEDED_BY_REVISION`, and re-derives the group's `posture`
    — which typically becomes `READY` with `posture_reason`
    `READY_ALL_CHECKS_PASSED`."

    Design: Corner/state_machines/publishing_a_second_runbook_revision_supersedes_the_first
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    second = fx.open_runbook(
        api,
        coordinator,
        group_id,
        estate["coordinator"]["id"],
        title="Ledger failover runbook, revision 2",
        validity_days=180,
    )
    second_step = fx.add_step(
        api,
        coordinator,
        second["id"],
        estate["operator"]["id"],
        step_number=1,
        description="Promote the ledger replica with the new script",
        expected_minutes=12,
        weight=10,
        covers_application_id=estate["app_core"]["id"],
    )
    fx.transition_runbook(api, coordinator, second["id"], "SUBMIT_FOR_REVIEW")
    fx.validate_step(api, estate["operator_headers"], second_step["id"])

    validated = fx.transition_runbook(api, coordinator, second["id"], "VALIDATE")

    assert_runbook_state(
        validated, "VALIDATED", stale_reason="NONE", readiness_score=100.00
    )
    assert validated["revision"] == 2
    assert_instant(validated["validated_at"], CLOCK_EPOCH)
    assert_runbook_state(
        fx.read_runbook(api, coordinator, estate["runbook"]["id"]),
        "SUPERSEDED",
        stale_reason="SUPERSEDED_BY_REVISION",
    )
    group = fx.read_group(api, coordinator, group_id)
    assert group["current_runbook_id"] == second["id"]
    assert_posture(group, "READY", "READY_ALL_CHECKS_PASSED")
    rows, meta = validate_paginated(
        api.list_runbooks(coordinator, params={"recovery_group_id": group_id})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {estate["runbook"]["id"], second["id"]}


def test_aborting_mid_flight_releases_the_reservation_and_is_terminal(api):
    """An abort stamps its own closure reason, frees capacity and accepts nothing more.

    PRD: "An exercise in trouble mid-flight is aborted instead: `IN_EXECUTION`
    moves to the terminal `ABORTED` with no precondition, `closure_reason` becomes
    `ABORTED_IN_EXECUTION`, and the site's `reserved_capacity_units` is recomputed
    downward by the exercise's `required_capacity_units`."

    Design: Corner/state_machines/abort_in_execution_stamps_aborted_reason_and_releases_capacity
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    site_id = estate["site_recovery"]["id"]
    exercise = fx.setup_exercise_in_execution(
        api,
        estate,
        name="Abort subject",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 2)

    aborted = validate_success(
        api.transition_execution(
            exercise["id"],
            f.execution_transition_payload(
                "ABORT", "Production incident on the primary site"
            ),
            coordinator,
        ),
        201,
    )

    assert_axes(
        aborted, execution_state="ABORTED", closure_reason="ABORTED_IN_EXECUTION"
    )
    assert aborted["rto_objective_minutes"] == 60
    assert aborted["rpo_objective_minutes"] == 15
    for field in (
        "achieved_rto_minutes",
        "achieved_rpo_minutes",
        "rto_met",
        "rpo_met",
        "failover_completed_at",
    ):
        assert aborted[field] is None, f"{field} should stay null after an abort"
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 0)
    validate_error(
        api.transition_execution(
            exercise["id"], f.execution_transition_payload("CLOSE"), coordinator
        ),
        ApiErrorId.ERR_INVALID_EXERCISE_STATE,
        409,
    )
