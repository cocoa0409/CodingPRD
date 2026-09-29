"""The pinned rejection ladder: which check answers first, and which is conditional."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    assert_finding_state,
    assert_instant,
    assert_posture,
    assert_runbook_state,
    assert_step_validation,
    factories as f,
    fixtures as fx,
)


def test_an_edge_from_a_node_to_itself_reports_self_dependency(api):
    """Identity is checked before the cycle rule, so the self edge names its own error.

    PRD: "A dependency edge's two endpoints are not the same node —
    `ERR_SELF_DEPENDENCY` (422), on dependency-edge creation." And: "When several
    checks could reject the same request, the server evaluates them in a fixed
    global order and reports the **first** failure only."

    Design: Corner/validations/dependency_edge_from_a_node_to_itself_rejected
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_ASSET_REGISTERED
    )
    coordinator = estate["coordinator_headers"]
    application_id = estate["app_core"]["id"]

    validate_error(
        api.create_dependency_edge(
            f.dependency_edge_payload(
                "APPLICATION", application_id, "APPLICATION", application_id, "HARD"
            ),
            coordinator,
        ),
        ApiErrorId.ERR_SELF_DEPENDENCY,
        422,
    )

    _, meta = validate_paginated(
        api.list_dependency_edges(
            coordinator, params={"from_node_id": application_id}
        )
    )
    assert meta["total_count"] == 0


def test_a_proposal_exactly_at_the_tier_ceiling_is_accepted(api):
    """Sixty minutes is inside the TIER_1 ceiling; sixty-one is over it.

    PRD: "The recovery time objective may not exceed one hour for `TIER_1`, four
    hours for `TIER_2`, or twenty-four hours for `TIER_3` — that is, 60, 240 and
    1440 minutes respectively — and a proposal that exceeds its tier's ceiling is
    rejected with `ERR_TIER_RTO_EXCEEDS_CAP`." And: "An accepted proposal stores
    the three proposed values, sets `tier_agreement_status` to `TIER_PROPOSED`, and
    records the acting `X-User-ID` in `proposed_by_id`."

    Design: Corner/validations/tier_rto_cap_accepts_exactly_sixty_and_rejects_sixty_one
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_SITES_REGISTERED
    )
    coordinator = estate["coordinator_headers"]
    at_the_cap = fx.register_application(
        api,
        coordinator,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-CAPA",
        name="Cap probe A",
        criticality_weight=4,
    )
    over_the_cap = fx.register_application(
        api,
        coordinator,
        business_owner_id=estate["business_owner"]["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-CAPB",
        name="Cap probe B",
        criticality_weight=4,
    )

    accepted = validate_success(
        api.propose_application_tier(
            at_the_cap["id"],
            f.tier_proposal_payload("TIER_1", 60, 15, "Exactly at both caps"),
            coordinator,
        ),
        201,
    )
    validate_error(
        api.propose_application_tier(
            over_the_cap["id"],
            f.tier_proposal_payload("TIER_1", 61, 15, "One minute over the cap"),
            coordinator,
        ),
        ApiErrorId.ERR_TIER_RTO_EXCEEDS_CAP,
        422,
    )

    assert accepted["tier_agreement_status"] == "TIER_PROPOSED"
    assert accepted["proposed_rto_minutes"] == 60
    assert accepted["proposed_rpo_minutes"] == 15
    assert accepted["proposed_by_id"] == estate["coordinator"]["id"]
    assert accepted["rto_minutes"] is None
    rejected = validate_success(
        api.get_application(over_the_cap["id"], coordinator)
    )
    assert rejected["tier_agreement_status"] == "DRAFT"
    assert rejected["proposed_tier"] is None


def test_an_observation_stamped_at_the_clock_is_stored_but_a_later_one_is_not(api):
    """Equality with the logical clock is on the accepting side of the check.

    PRD: "A measurement dated after the current logical clock is nonsense and is
    rejected with `ERR_OBSERVATION_IN_FUTURE`." And: "`observed_at` is at or before
    the current logical clock — `ERR_OBSERVATION_IN_FUTURE` (422), on appending a
    replication observation."

    Design: Corner/validations/observation_exactly_at_the_clock_is_accepted_and_one_second_ahead_rejected
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_ASSET_REGISTERED
    )
    operator = estate["operator_headers"]
    asset_id = estate["asset_db"]["id"]

    stored = validate_success(
        api.create_replication_observation(
            asset_id, f.replication_observation_payload(CLOCK_EPOCH, 120, 300), operator
        ),
        201,
    )
    validate_error(
        api.create_replication_observation(
            asset_id,
            f.replication_observation_payload("2026-08-01T00:00:01Z", 120, 300),
            operator,
        ),
        ApiErrorId.ERR_OBSERVATION_IN_FUTURE,
        422,
    )

    assert_instant(stored["observed_at"], CLOCK_EPOCH)
    _, meta = validate_paginated(
        api.list_replication_observations(asset_id, estate["coordinator_headers"])
    )
    assert meta["total_count"] == 1


def test_the_agreement_check_only_fires_for_a_step_that_covers_an_application(api):
    """The coverless step validates while its covering sibling is refused.

    PRD: "A step that names a `covers_application_id` covers an application whose
    `tier_agreement_status` is `AGREED` — `ERR_STEP_COVERS_UNAGREED_APPLICATION`
    (422), on step validation." And: "A step may name a `covers_application_id`
    when it recovers a particular application and a `covers_asset_id` when it
    recovers a particular asset; either may be null — the application reference is
    null when the step covers infrastructure only, and the asset reference is null
    when the step covers an application only."

    Design: Corner/validations/coverless_step_skips_the_agreement_check_that_a_covering_step_fails
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_APPLICATION_PROPOSED
    )
    coordinator = estate["coordinator_headers"]
    operator = estate["operator_headers"]
    group = fx.create_recovery_group(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        lead_coordinator_id=estate["coordinator"]["id"],
        group_code="RG-C",
        name="Conditional probe group",
        recovery_order=4,
    )
    runbook = fx.open_runbook(
        api,
        coordinator,
        group["id"],
        estate["coordinator"]["id"],
        title="Conditional probe runbook",
    )
    covering_step = fx.add_step(
        api,
        coordinator,
        runbook["id"],
        estate["operator"]["id"],
        step_number=1,
        description="Promote the unagreed application",
        expected_minutes=10,
        weight=10,
        covers_application_id=estate["app_core"]["id"],
    )
    coverless_step = fx.add_step(
        api,
        coordinator,
        runbook["id"],
        estate["operator"]["id"],
        step_number=2,
        description="Announce the cutover on the bridge call",
        expected_minutes=5,
        weight=10,
    )
    fx.transition_runbook(api, coordinator, runbook["id"], "SUBMIT_FOR_REVIEW")

    validated = fx.validate_step(
        api, operator, coverless_step["id"], note="No application coverage, nothing to check"
    )
    validate_error(
        api.validate_runbook_step(
            covering_step["id"],
            f.step_validation_payload("Covers an application that is still only proposed"),
            operator,
        ),
        ApiErrorId.ERR_STEP_COVERS_UNAGREED_APPLICATION,
        422,
    )

    assert_step_validation(validated, "VALIDATED", CLOCK_EPOCH)
    assert_step_validation(
        fx.read_step(api, coordinator, covering_step["id"]), "PENDING"
    )
    assert_runbook_state(
        fx.read_runbook(api, coordinator, runbook["id"]), "IN_REVIEW", readiness_score=50.00
    )
    assert_posture(
        fx.read_group(api, coordinator, group["id"]),
        "RESTRICTED",
        "NO_VALIDATED_RUNBOOK",
    )


def test_the_finding_state_check_answers_before_the_retest_scope_check(api):
    """One payload draws two different errors depending on where the finding sits.

    PRD: "The finding's `state` is a declared from-state for the requested action —
    `ERR_INVALID_FINDING_STATE` (409), on finding transitions." And: "The nominated
    re-test exercise scopes the finding's own recovery group —
    `ERR_RETEST_SCOPE_MISMATCH` (422), on a finding transition whose `action` is
    `SCHEDULE_RETEST`."

    Design: Corner/validations/retest_scope_check_runs_only_after_the_finding_state_check
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_GROUP_CREATED)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    source = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
        name="Source exercise",
    )
    unscoped_retest = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-09-20T00:00:00Z",
        planned_end_at="2026-09-20T06:00:00Z",
        name="Unscoped retest candidate",
    )
    finding = fx.raise_finding(
        api,
        coordinator,
        source["id"],
        group_id,
        severity="HIGH",
        title="Runbook step ownership unclear",
        description="Nobody could name the owner of the promotion step.",
    )

    validate_error(
        api.transition_finding(
            finding["id"],
            f.finding_transition_payload(
                "SCHEDULE_RETEST", retest_exercise_id=unscoped_retest["id"]
            ),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_FINDING_STATE,
        409,
    )
    fx.drive_finding(
        api, coordinator, finding["id"], "ASSIGN", owner_id=estate["operator"]["id"]
    )
    remediated = fx.drive_finding(
        api,
        coordinator,
        finding["id"],
        "REMEDIATE",
        note="Ownership recorded on every step",
    )
    assert_finding_state(remediated, "REMEDIATED")
    assert remediated["owner_id"] == estate["operator"]["id"]

    validate_error(
        api.transition_finding(
            finding["id"],
            f.finding_transition_payload(
                "SCHEDULE_RETEST", retest_exercise_id=unscoped_retest["id"]
            ),
            coordinator,
        ),
        ApiErrorId.ERR_RETEST_SCOPE_MISMATCH,
        422,
    )

    still_remediated = fx.read_finding(api, coordinator, finding["id"])
    assert_finding_state(still_remediated, "REMEDIATED")
    assert still_remediated["retest_exercise_id"] is None
    assert fx.read_group(api, coordinator, group_id)["open_finding_count"] == 1
