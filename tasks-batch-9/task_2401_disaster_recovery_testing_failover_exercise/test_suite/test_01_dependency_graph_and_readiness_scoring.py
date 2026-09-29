"""Critical-path projection over the dependency graph and runbook readiness scoring."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    assert_axes,
    assert_instant,
    assert_posture,
    assert_projection,
    assert_runbook_state,
    assert_score,
    assert_step_validation,
    factories as f,
    fixtures as fx,
)


def test_projection_follows_the_longest_hard_dependency_chain(api):
    """The projection is the heaviest directed path over the group's HARD edges.

    PRD: "Over that directed subgraph — always acyclic, because cycle creation is
    blocked at write time — the server finds the directed path whose total node
    weight is greatest, and `projected_recovery_minutes` is that total." And:
    "`recovery_sequence` is the ordered list of node ids along that winning path,
    running from the most dependent node at the head down to the deepest
    dependency at the tail, following the direction of the edges."

    Design: Difficulty/combinatorial_formula/projected_recovery_longest_hard_path_ignores_soft_edges
    """
    estate = fx.setup_soft_edge_graph(api)
    coordinator = estate["coordinator_headers"]

    fx.create_dependency_edge(
        api,
        coordinator,
        from_node_kind="ASSET",
        from_node_id=estate["asset_db"]["id"],
        to_node_kind="ASSET",
        to_node_id=estate["asset_net"]["id"],
        edge_kind="HARD",
    )

    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert_projection(
        group,
        92,
        [
            estate["app_core"]["id"],
            estate["asset_db"]["id"],
            estate["asset_net"]["id"],
        ],
    )


def test_soft_edges_never_enter_the_projection(api):
    """A SOFT edge documents a relationship without lengthening the critical path.

    PRD: "`SOFT` edges are documentation only, contributing exactly zero to any
    projection and recorded without touching a single derived field."

    Design: Difficulty/combinatorial_formula/projected_recovery_longest_hard_path_ignores_soft_edges
    """
    estate = fx.setup_soft_edge_graph(api)
    coordinator = estate["coordinator_headers"]

    assert estate["soft_edge"]["edge_kind"] == "SOFT"
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert_projection(group, 80, [estate["app_core"]["id"], estate["asset_db"]["id"]])

    fx.create_dependency_edge(
        api,
        coordinator,
        from_node_kind="ASSET",
        from_node_id=estate["asset_db"]["id"],
        to_node_kind="ASSET",
        to_node_id=estate["asset_net"]["id"],
        edge_kind="HARD",
    )

    group = fx.read_group(api, coordinator, estate["group"]["id"])
    # Counting the SOFT edge as well would have produced a 137-minute path
    # through the edge application; the projection stays on the HARD path.
    assert group["projected_recovery_minutes"] == 92


def test_readiness_rounds_each_step_contribution_before_summing(api):
    """Three equally weighted fresh steps score 99.99, not 100.00.

    PRD: "Three steps of `weight` 10, all `VALIDATED` today, therefore produce
    33.33 plus 33.33 plus 33.33, for a `readiness_score` of 99.99 rather than
    100.00."

    Design: Difficulty/combinatorial_formula/readiness_round_each_contribution_then_sum_yields_99_99
    """
    estate = fx.setup_three_equally_weighted_validated_steps(api)

    runbook = fx.transition_runbook(
        api, estate["coordinator_headers"], estate["runbook"]["id"], "VALIDATE"
    )

    assert_runbook_state(runbook, "VALIDATED", readiness_score=99.99)
    assert runbook["readiness_score"] != 100.00
    assert_instant(runbook["validated_at"], CLOCK_EPOCH)


def test_readiness_sum_is_not_rounded_again_after_the_contributions(api):
    """The sum of the rounded contributions is published as it stands.

    PRD: "The runbook's `readiness_score` is the plain sum of those per-step
    contributions, with **no further rounding applied to the sum**."

    Design: Difficulty/combinatorial_formula/readiness_round_each_contribution_then_sum_yields_99_99
    """
    estate = fx.setup_three_equally_weighted_validated_steps(api)
    coordinator = estate["coordinator_headers"]

    fx.transition_runbook(api, coordinator, estate["runbook"]["id"], "VALIDATE")

    runbook = fx.read_runbook(api, coordinator, estate["runbook"]["id"])
    assert_score(runbook["readiness_score"], 99.99)
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert group["current_runbook_id"] == estate["runbook"]["id"]
    assert_posture(group, "READY", "READY_ALL_CHECKS_PASSED")


def test_readiness_exactly_at_the_eighty_floor_admits_the_scope_item(api):
    """A runbook whose decayed score is exactly 80.00 still passes the floor.

    PRD: "The group must have a non-null `current_runbook_id` whose runbook is
    `VALIDATED` and whose `readiness_score`, recomputed against the current
    logical clock as part of this very request, is at least 80.00."

    Design: Difficulty/boundary_precision_check/readiness_exactly_at_the_eighty_floor_scopes_and_one_step_below_rejects
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-11-20T00:00:00Z",
        planned_end_at="2026-11-20T06:00:00Z",
        name="Readiness floor rehearsal",
    )

    fx.set_logical_clock(api, "2026-10-12T00:00:00Z")
    scope_item = validate_success(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["group"]["id"], exercise["version"]),
            coordinator,
        ),
        201,
    )

    assert scope_item["runbook_id_snapshot"] == estate["runbook"]["id"]
    assert scope_item["group_projected_recovery_minutes_snapshot"] == 92
    assert_axes(
        fx.read_exercise(api, coordinator, exercise["id"]), execution_state="SCOPED"
    )


def test_readiness_one_day_below_the_floor_rejects_the_scope_item(api):
    """One further day of decay drops the score under the floor and blocks scoping.

    PRD: "Anything less — no current runbook, a runbook that is `DRAFT`,
    `IN_REVIEW`, `STALE` or `SUPERSEDED`, or a score that has decayed below the
    floor — is rejected with `ERR_RUNBOOK_STALE`."

    Design: Difficulty/boundary_precision_check/readiness_exactly_at_the_eighty_floor_scopes_and_one_step_below_rejects
    """
    estate = fx.setup_two_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-11-20T00:00:00Z",
        planned_end_at="2026-11-20T06:00:00Z",
        name="Readiness floor rehearsal",
    )

    fx.set_logical_clock(api, "2026-10-13T00:00:00Z")
    validate_error(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["group"]["id"], exercise["version"]),
            coordinator,
        ),
        ApiErrorId.ERR_RUNBOOK_STALE,
        422,
    )

    rejected = fx.read_exercise(api, coordinator, exercise["id"])
    assert_axes(rejected, execution_state="DRAFT")
    assert rejected["version"] == exercise["version"]
    assert rejected["required_capacity_units"] == 0
    validate_success(api.refresh_posture(estate["group"]["id"], coordinator))
    runbook = fx.read_runbook(api, coordinator, estate["runbook"]["id"])
    assert_score(runbook["readiness_score"], 79.72)


def test_step_covering_an_unagreed_application_cannot_be_validated(api):
    """Validation refuses a step whose covered application has not agreed its tier.

    PRD: "When the step names a `covers_application_id`, the covered
    application's `tier_agreement_status` must be `AGREED`; validating a step
    that covers an unagreed application is rejected with
    `ERR_STEP_COVERS_UNAGREED_APPLICATION`."

    Design: Difficulty/cross_entity_state_dependency/step_validation_depends_on_covered_application_being_agreed
    """
    estate = fx.setup_unagreed_coverage_scenario(api)

    validate_error(
        api.validate_runbook_step(
            estate["step"]["id"], f.step_validation_payload(), estate["operator_headers"]
        ),
        ApiErrorId.ERR_STEP_COVERS_UNAGREED_APPLICATION,
        422,
    )

    coordinator = estate["coordinator_headers"]
    step = fx.read_step(api, coordinator, estate["step"]["id"])
    assert_step_validation(step, "PENDING")
    assert step["last_validated_at"] is None
    runbook = fx.read_runbook(api, coordinator, estate["runbook"]["id"])
    assert_runbook_state(runbook, "IN_REVIEW", readiness_score=0.00)


def test_step_validation_succeeds_once_the_covered_tier_is_agreed(api):
    """With the tier agreed the same validation lands and refreshes readiness.

    PRD: "In all three cases `last_validated_at` becomes the current logical
    clock, and the server then recomputes the owning runbook's `readiness_score`
    and, after that, the owning recovery group's `posture`."

    Design: Difficulty/cross_entity_state_dependency/step_validation_depends_on_covered_application_being_agreed
    """
    estate = fx.setup_unagreed_coverage_scenario(api)
    coordinator = estate["coordinator_headers"]

    validate_success(
        api.decide_application_tier(
            estate["negotiating_application"]["id"],
            f.tier_decision_payload("AGREE", "Agreed as proposed"),
            estate["owner_headers"],
        ),
        201,
    )
    step = fx.validate_step(api, estate["operator_headers"], estate["step"]["id"])

    assert_step_validation(step, "VALIDATED", CLOCK_EPOCH)
    runbook = fx.read_runbook(api, coordinator, estate["runbook"]["id"])
    assert_runbook_state(runbook, "IN_REVIEW", readiness_score=100.00)
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert_posture(group, "RESTRICTED", "NO_VALIDATED_RUNBOOK")
