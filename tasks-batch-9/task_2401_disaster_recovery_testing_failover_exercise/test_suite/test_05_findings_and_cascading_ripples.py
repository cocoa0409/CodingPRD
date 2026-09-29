"""Finding remediation loops and the three ordered cascades they and re-tiering fire."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_axes,
    assert_finding_state,
    assert_posture,
    assert_reserved_capacity,
    assert_runbook_state,
    assert_step_validation,
    factories as f,
    fixtures as fx,
)


def test_failed_retest_of_a_high_finding_does_not_escalate(api):
    """Severity below CRITICAL never escalates, however often the re-test fails.

    PRD: "A `HIGH`, `MEDIUM` or `LOW` finding never escalates however many times
    it fails, and a `CRITICAL` finding that has failed only once does not
    either."

    Design: Difficulty/non_linear_state_machine/finding_retest_failure_loops_back_to_remediation_assigned
    """
    estate = fx.setup_retest_scheduled_finding(api, severity="HIGH")
    coordinator = estate["coordinator_headers"]

    failed = fx.drive_finding(
        api,
        coordinator,
        estate["finding"]["id"],
        "RECORD_RETEST_RESULT",
        retest_result="FAILED",
        note="Reroute still manual",
    )

    assert_finding_state(failed, "RETEST_FAILED", retest_failure_count=1, escalated=False)
    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "READY",
        "READY_ALL_CHECKS_PASSED",
    )


def test_reassignment_after_a_failed_retest_retains_the_counter(api):
    """The loop back to remediation keeps the failure count and the re-test vehicle.

    PRD: "From `RETEST_FAILED`, `ASSIGN` sends the finding back to
    `REMEDIATION_ASSIGNED` with a new `owner_id` — again required to be an
    `ACTIVE` stakeholder — while `retest_failure_count` and `escalated` are
    deliberately retained across that loop."

    Design: Difficulty/non_linear_state_machine/finding_retest_failure_loops_back_to_remediation_assigned
    """
    estate = fx.setup_retest_scheduled_finding(api, severity="HIGH")
    coordinator = estate["coordinator_headers"]
    fx.drive_finding(
        api,
        coordinator,
        estate["finding"]["id"],
        "RECORD_RETEST_RESULT",
        retest_result="FAILED",
    )

    reassigned = fx.drive_finding(
        api,
        coordinator,
        estate["finding"]["id"],
        "ASSIGN",
        owner_id=estate["coordinator"]["id"],
    )

    assert_finding_state(
        reassigned, "REMEDIATION_ASSIGNED", retest_failure_count=1, escalated=False
    )
    assert reassigned["owner_id"] == estate["coordinator"]["id"]
    assert reassigned["retest_exercise_id"] == estate["retest_exercise"]["id"]
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert group["open_finding_count"] == 1
    assert_posture(group, "READY", "READY_ALL_CHECKS_PASSED")


def test_raising_findings_lifts_the_group_open_finding_count(api):
    """Each newly raised finding is counted against its recovery group.

    PRD: "A new finding starts in `state` `OPEN` with `owner_id` null,
    `retest_exercise_id` null, `retest_failure_count` 0 and `escalated` false, and
    raising it recomputes the group's `open_finding_count`, which rises by 1."

    Design: Difficulty/compensating_invariant/open_finding_count_returns_to_zero_after_every_finding_is_withdrawn
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Finding accounting rehearsal",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    first = fx.raise_finding(
        api,
        coordinator,
        exercise["id"],
        group_id,
        severity="MEDIUM",
        title="Runbook wording was ambiguous",
        description="Step 2 wording confused the operator.",
    )
    assert_finding_state(first, "OPEN", retest_failure_count=0, escalated=False)
    assert first["owner_id"] is None
    assert fx.read_group(api, coordinator, group_id)["open_finding_count"] == 1

    fx.raise_finding(
        api,
        coordinator,
        exercise["id"],
        group_id,
        severity="MEDIUM",
        title="Contact list was out of date",
        description="Two escalation contacts had left the firm.",
    )

    assert fx.read_group(api, coordinator, group_id)["open_finding_count"] == 2


def test_withdrawing_every_finding_returns_the_count_to_zero(api):
    """Withdrawal is recounted from the surviving findings, not deducted blindly.

    PRD: "Every movement into `CLOSED` or `WITHDRAWN` recomputes the group's
    `open_finding_count`, which falls by 1, and then re-derives the group's
    `posture`."

    Design: Difficulty/compensating_invariant/open_finding_count_returns_to_zero_after_every_finding_is_withdrawn
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Finding accounting rehearsal",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    first = fx.raise_finding(
        api,
        coordinator,
        exercise["id"],
        group_id,
        severity="MEDIUM",
        title="Runbook wording was ambiguous",
        description="Step 2 wording confused the operator.",
    )
    second = fx.raise_finding(
        api,
        coordinator,
        exercise["id"],
        group_id,
        severity="MEDIUM",
        title="Contact list was out of date",
        description="Two escalation contacts had left the firm.",
    )

    withdrawn_first = fx.drive_finding(api, coordinator, first["id"], "WITHDRAW")
    assert_finding_state(withdrawn_first, "WITHDRAWN")
    assert fx.read_group(api, coordinator, group_id)["open_finding_count"] == 1
    withdrawn_second = fx.drive_finding(api, coordinator, second["id"], "WITHDRAW")
    assert_finding_state(withdrawn_second, "WITHDRAWN")

    group = fx.read_group(api, coordinator, group_id)
    assert group["open_finding_count"] == 0
    assert_posture(group, "READY", "READY_ALL_CHECKS_PASSED")
    assert_runbook_state(
        fx.read_runbook(api, coordinator, estate["runbook"]["id"]),
        "VALIDATED",
        readiness_score=100.00,
    )


def test_retiering_invalidates_only_the_steps_covering_that_application(api):
    """The re-tier counter moves and exactly one step loses its validation.

    PRD: "Hop 2, caused by hop 1, moves every runbook step whose
    `covers_application_id` is that application and whose `validation_status` is
    `VALIDATED` to `INVALIDATED`."

    Design: Difficulty/transitive_cascade/cascade_a_retier_invalidates_step_stales_runbook_restricts_group_reverts_schedule_releases_capacity
    """
    estate = fx.setup_cascade_a_scenario(api)
    coordinator = estate["coordinator_headers"]

    validate_success(
        api.propose_application_tier(
            estate["app_core"]["id"],
            f.tier_proposal_payload("TIER_1", 45, 10, "Tighter regulatory promise"),
            coordinator,
        ),
        201,
    )

    application = validate_success(
        api.get_application(estate["app_core"]["id"], coordinator)
    )
    assert application["retier_count"] == 1
    assert application["tier_agreement_status"] == "TIER_PROPOSED"
    assert application["tier"] == "TIER_1"
    assert application["rto_minutes"] == 60
    assert application["rpo_minutes"] == 15
    covering = fx.read_step(api, coordinator, estate["step_core"]["id"])
    assert_step_validation(covering, "INVALIDATED")
    assert covering["last_validated_at"] is not None
    assert_step_validation(
        fx.read_step(api, coordinator, estate["step_db"]["id"]), "VALIDATED"
    )
    assert_step_validation(
        fx.read_step(api, coordinator, estate["step_net"]["id"]), "VALIDATED"
    )


def test_retiering_stales_the_runbook_and_releases_the_scheduled_reservation(api):
    """The ripple carries on to the runbook, the posture, the exercise and the site.

    PRD: "Hop 5, caused by hop 4, reverts every exercise in `execution_state`
    `SCHEDULED` that holds a scope item on such a group back to `SCOPED`, leaving
    its `closure_reason` at `NONE`."

    Design: Difficulty/transitive_cascade/cascade_a_retier_invalidates_step_stales_runbook_restricts_group_reverts_schedule_releases_capacity
    """
    estate = fx.setup_cascade_a_scenario(api)
    coordinator = estate["coordinator_headers"]
    site_id = estate["site_recovery"]["id"]
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 2)

    validate_success(
        api.propose_application_tier(
            estate["app_core"]["id"],
            f.tier_proposal_payload("TIER_1", 45, 10, "Tighter regulatory promise"),
            coordinator,
        ),
        201,
    )

    assert_runbook_state(
        fx.read_runbook(api, coordinator, estate["runbook"]["id"]),
        "STALE",
        stale_reason="APPLICATION_RETIERED",
        readiness_score=75.00,
    )
    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "RESTRICTED",
        "RUNBOOK_STALE",
    )
    reverted = fx.read_exercise(api, coordinator, estate["scheduled_exercise"]["id"])
    assert_axes(reverted, execution_state="SCOPED", closure_reason="NONE")
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 0)


def test_a_single_failed_retest_of_a_critical_finding_freezes_nothing(api):
    """Escalation waits for the second failure even when the finding is CRITICAL.

    PRD: "Hop 2, caused by hop 1, sets `escalated` to true when the count has
    reached at least 2 and the finding's `severity` is `CRITICAL`."

    Design: Difficulty/transitive_cascade/cascade_b_second_retest_failure_escalates_freezes_group_cancels_exercises_releases_capacity
    """
    estate = fx.setup_cascade_b_scenario(api)
    coordinator = estate["coordinator_headers"]

    finding = fx.read_finding(api, coordinator, estate["finding"]["id"])

    assert_finding_state(
        finding, "RETEST_SCHEDULED", retest_failure_count=1, escalated=False
    )
    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "READY",
        "READY_ALL_CHECKS_PASSED",
    )
    assert_axes(
        fx.read_exercise(api, coordinator, estate["scheduled_exercise"]["id"]),
        execution_state="SCHEDULED",
    )
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 6
    )


def test_second_failed_retest_freezes_the_group_and_cancels_its_exercises(api):
    """The second failure escalates, freezes the group and empties its calendar.

    PRD: "Hop 4, caused by hop 3, cancels every exercise holding a scope item on
    that group whose `execution_state` is `SCOPED`, `PENDING_IMPACT_APPROVAL`,
    `APPROVED` or `SCHEDULED`, setting `execution_state` to `CANCELLED` and
    `closure_reason` to `CANCELLED_GROUP_FROZEN`."

    Design: Difficulty/transitive_cascade/cascade_b_second_retest_failure_escalates_freezes_group_cancels_exercises_releases_capacity
    """
    estate = fx.setup_cascade_b_scenario(api)
    coordinator = estate["coordinator_headers"]

    escalated = fx.drive_finding(
        api,
        coordinator,
        estate["finding"]["id"],
        "RECORD_RETEST_RESULT",
        retest_result="FAILED",
        note="Second re-test lost rows again",
    )

    assert_finding_state(
        escalated, "RETEST_FAILED", retest_failure_count=2, escalated=True
    )
    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "FROZEN",
        "OPEN_CRITICAL_FINDING",
    )
    for key in ("source_exercise", "retest_exercise", "scheduled_exercise"):
        assert_axes(
            fx.read_exercise(api, coordinator, estate[key]["id"]),
            execution_state="CANCELLED",
            closure_reason="CANCELLED_GROUP_FROZEN",
        )
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 0
    )
    assert_runbook_state(
        fx.read_runbook(api, coordinator, estate["runbook"]["id"]),
        "VALIDATED",
        readiness_score=100.00,
    )


def test_suspending_a_step_owner_invalidates_every_step_they_own(api):
    """Suspension reaches through ownership to every step the person validated.

    PRD: "Hop 2, caused by hop 1, moves every runbook step whose `owner_id` is
    that person and whose `validation_status` is `VALIDATED` to `INVALIDATED`."

    Design: Difficulty/transitive_cascade/cascade_c_owner_suspension_invalidates_all_steps_zeroes_readiness_restricts_group
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]

    suspended = validate_success(
        api.patch_stakeholder(
            estate["operator"]["id"], {"status": "SUSPENDED"}, estate["admin_headers"]
        )
    )

    assert suspended["status"] == "SUSPENDED"
    for key in ("step_core", "step_db", "step_net"):
        assert_step_validation(
            fx.read_step(api, coordinator, estate[key]["id"]), "INVALIDATED"
        )


def test_suspension_zeroes_readiness_and_restricts_the_group(api):
    """With every step invalidated the runbook stales and the group is restricted.

    PRD: "Hop 3, caused by hop 2, moves each owning runbook whose `status` is
    `VALIDATED` to `STALE` with `stale_reason` `STEP_OWNER_SUSPENDED` and
    recomputes its `readiness_score`."

    Design: Difficulty/transitive_cascade/cascade_c_owner_suspension_invalidates_all_steps_zeroes_readiness_restricts_group
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]

    validate_success(
        api.patch_stakeholder(
            estate["operator"]["id"], {"status": "SUSPENDED"}, estate["admin_headers"]
        )
    )

    assert_runbook_state(
        fx.read_runbook(api, coordinator, estate["runbook"]["id"]),
        "STALE",
        stale_reason="STEP_OWNER_SUSPENDED",
        readiness_score=0.00,
    )
    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "RESTRICTED",
        "RUNBOOK_STALE",
    )
    application = validate_success(
        api.get_application(estate["app_core"]["id"], coordinator)
    )
    assert application["retier_count"] == 0
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 0
    )
