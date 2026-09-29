"""Objective baselines, manifest counting, tabletop constants and the decay curve."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CLOCK_EPOCH,
    assert_achieved,
    assert_axes,
    assert_finding_state,
    assert_impact_scores,
    assert_instant,
    assert_objectives,
    assert_posture,
    assert_projection,
    assert_reserved_capacity,
    assert_runbook_state,
    assert_score,
    assert_step_validation,
    factories as f,
    fixtures as fx,
)


def test_objectives_take_the_tightest_value_of_each_field_separately(api):
    """The baseline is a per-field minimum drawn from two different applications.

    PRD: "Those baseline applications are exactly the `AGREED` members of the
    in-scope groups; `rto_objective_minutes` is the smallest `rto_minutes` among
    them and `rpo_objective_minutes` is the smallest `rpo_minutes` among them —
    the tightest promise made to any in-scope business owner becomes the whole
    exercise's target." And: "Starting stamps `execution_started_at` with the
    current logical clock and pins the objectives the rehearsal will be judged
    against."

    Design: Corner/calculations/objectives_baseline_takes_the_tightest_rto_and_rpo_across_two_applications
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    edge = fx.register_application(
        api,
        coordinator,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-EDGE",
        name="Edge portal",
        criticality_weight=8,
    )
    fx.agree_application_tier(
        api,
        coordinator,
        estate["owner_headers"],
        edge["id"],
        proposed_tier="TIER_2",
        proposed_rto_minutes=45,
        proposed_rpo_minutes=60,
    )
    fx.assign_application(api, coordinator, edge["id"], estate["group"]["id"])
    exercise = fx.setup_scheduled_exercise(
        api,
        estate,
        name="Baseline subject",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    started = fx.drive_execution(api, coordinator, exercise["id"], "START")

    assert_objectives(started, 45, 15)
    assert_axes(started, execution_state="IN_EXECUTION")
    assert_instant(started["execution_started_at"], CLOCK_EPOCH)
    assert_impact_scores(started, 38.50, 39.50, "LEVEL_1")
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert_projection(group, 80)


def test_a_withdrawn_finding_is_left_out_of_the_manifest(api):
    """Every scope item and step execution counts; the withdrawn finding does not.

    PRD: "Submission computes `manifest_line_count`: one header line, plus one line
    for each scope item of the evidenced exercise, plus one line for each step
    execution of that exercise regardless of its `outcome`, plus one line for each
    finding raised against that exercise whose `state` is anything other than
    `WITHDRAWN`." And: "The group's `open_finding_count` is a plain aggregate: the
    number of findings whose `recovery_group_id` is this group and whose `state` is
    one of `OPEN`, `REMEDIATION_ASSIGNED`, `REMEDIATED`, `RETEST_SCHEDULED` or
    `RETEST_FAILED`."

    Design: Corner/calculations/withdrawn_finding_is_excluded_from_the_evidence_manifest
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    fx.record_replication_observation(
        api,
        estate["operator_headers"],
        estate["asset_db"]["id"],
        CLOCK_EPOCH,
        replication_lag_seconds=60,
        unreplicated_txn_count=100,
    )
    exercise = fx.setup_exercise_in_execution(
        api,
        estate,
        name="Manifest subject",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    fx.record_step_execution(
        api,
        coordinator,
        exercise["id"],
        estate["step_core"]["id"],
        elapsed_seconds=0,
        outcome="SKIPPED",
        notes="Skipped, dependency unavailable",
    )
    fx.drive_execution(api, coordinator, exercise["id"], "COMPLETE_FAILOVER")
    fx.drive_both_axes_to_terminal(api, estate["operator_headers"], exercise["id"])
    fx.drive_execution(api, coordinator, exercise["id"], "CLOSE")
    kept = fx.raise_finding(
        api,
        coordinator,
        exercise["id"],
        group_id,
        severity="HIGH",
        title="Replica promotion script drifted",
        description="The promotion script referenced a retired hostname.",
    )
    dropped = fx.raise_finding(
        api,
        estate["liaison_headers"],
        exercise["id"],
        group_id,
        severity="MEDIUM",
        title="Duplicate raise",
        description="Raised twice by two observers.",
    )
    fx.drive_finding(api, coordinator, dropped["id"], "WITHDRAW")
    package = fx.open_evidence_package(
        api, estate["liaison_headers"], exercise["id"], estate["audit_liaison"]["id"]
    )

    submitted = fx.transition_evidence(
        api, estate["liaison_headers"], package["id"], "SUBMIT"
    )

    assert submitted["state"] == "SUBMITTED"
    assert submitted["manifest_line_count"] == 4
    assert_finding_state(fx.read_finding(api, coordinator, dropped["id"]), "WITHDRAWN")
    assert_finding_state(fx.read_finding(api, coordinator, kept["id"]), "OPEN")
    group = fx.read_group(api, coordinator, group_id)
    assert group["open_finding_count"] == 1
    assert_posture(group, "READY", "READY_ALL_CHECKS_PASSED")
    assert_achieved(
        fx.read_exercise(api, coordinator, exercise["id"]),
        achieved_rto_minutes=0,
        rto_met=True,
    )


def test_a_tabletop_takes_the_lowest_base_and_reserves_nothing(api):
    """The discussion-only rehearsal scores from base 5 and books no capacity.

    PRD: "It also stores `capacity_units_contributed`, which is decided purely by
    the exercise's `exercise_type`: a `TABLETOP` rehearsal occupies no capacity at
    all and contributes 0 units, a `COMPONENT_FAILOVER` contributes 2 units per
    scoped group, and a `FULL_SITE_FAILOVER` contributes 6 units per scoped group."
    And: "**The provisional score** is a base figure for the rehearsal's ambition —
    5 for a `TABLETOP`, 20 for a `COMPONENT_FAILOVER`, 40 for a
    `FULL_SITE_FAILOVER` — plus the criticality component plus the capacity
    component, the total rounded half up to two decimal places."

    Design: Corner/calculations/tabletop_exercise_applies_base_five_and_zero_capacity_units
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    site_id = estate["site_recovery"]["id"]
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=site_id,
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T02:00:00Z",
        name="Tabletop walkthrough",
        exercise_type="TABLETOP",
    )
    scope_item = fx.scope_group(
        api, coordinator, exercise["id"], estate["group"]["id"]
    )
    assert scope_item["capacity_units_contributed"] == 0
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 0)

    submitted = fx.submit_impact(api, coordinator, exercise["id"])

    assert submitted["required_capacity_units"] == 0
    assert_impact_scores(submitted, 15.00, 16.00, "LEVEL_1")
    assert_axes(submitted, execution_state="PENDING_IMPACT_APPROVAL")
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 0)


def test_revalidating_a_step_restarts_its_decay_curve(api):
    """Decay is measured from the step's own validation instant, not the runbook's.

    PRD: "Validation moves `validation_status` from `PENDING` to `VALIDATED` or
    from `INVALIDATED` back to `VALIDATED`, and it is also accepted on a step that
    is already `VALIDATED` — a re-validation that leaves `validation_status` at
    `VALIDATED` but advances `last_validated_at` to the current logical clock,
    resetting the decay origin without touching the runbook's own `validated_at`."

    Design: Corner/calculations/revalidating_a_step_restarts_the_readiness_decay_curve
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    runbook_id = estate["runbook"]["id"]
    fx.set_logical_clock(api, "2026-09-10T00:00:00Z")

    refreshed = validate_success(
        api.refresh_posture(estate["group"]["id"], coordinator), 200
    )
    assert_posture(refreshed, "READY", "READY_ALL_CHECKS_PASSED")
    assert_score(
        fx.read_runbook(api, coordinator, runbook_id)["readiness_score"], 88.89
    )

    step = fx.validate_step(
        api,
        estate["operator_headers"],
        estate["step_core"]["id"],
        note="Re-walked the promotion script",
    )

    assert_step_validation(step, "VALIDATED", "2026-09-10T00:00:00Z")
    runbook = fx.read_runbook(api, coordinator, runbook_id)
    assert_runbook_state(runbook, "VALIDATED", readiness_score=100.00)
    assert_instant(runbook["validated_at"], CLOCK_EPOCH)


def test_validation_makes_the_group_ready_within_the_same_request(api):
    """The transition itself re-derives the group, so the next read already agrees.

    PRD: "On reaching `VALIDATED`, the server stamps `validated_at` with the
    current logical clock, resets `stale_reason` to `NONE`, recomputes
    `readiness_score`, re-points the owning group's `current_runbook_id` at this
    revision, marks any earlier revision of the same group `SUPERSEDED` with
    `stale_reason` `SUPERSEDED_BY_REVISION`, and re-derives the group's `posture` —
    which typically becomes `READY` with `posture_reason` `READY_ALL_CHECKS_PASSED`."

    Design: Corner/consistency_model/runbook_validation_makes_the_group_ready_in_the_same_request
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_STEP_VALIDATED)
    coordinator = estate["coordinator_headers"]

    validated = validate_success(
        api.transition_runbook(
            estate["runbook"]["id"], f.runbook_transition_payload("VALIDATE"), coordinator
        ),
        201,
    )

    assert_score(validated["readiness_score"], 100.00)
    group = fx.read_group(api, estate["liaison_headers"], estate["group"]["id"])
    assert_posture(group, "READY", "READY_ALL_CHECKS_PASSED")
    assert group["current_runbook_id"] == estate["runbook"]["id"]
    assert_projection(group, 80)
    runbook = fx.read_runbook(api, coordinator, estate["runbook"]["id"])
    assert_runbook_state(runbook, "VALIDATED", stale_reason="NONE")
    assert_instant(runbook["validated_at"], CLOCK_EPOCH)
