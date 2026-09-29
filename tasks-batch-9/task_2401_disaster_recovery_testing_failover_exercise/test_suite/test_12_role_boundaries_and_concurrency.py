"""Exclusive and shared operations, segregation of duties, and the concurrency layer."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    DEFAULT_VALIDITY_DAYS,
    PLATFORM_ADMIN_HEADERS,
    assert_axes,
    assert_finding_state,
    assert_impact_scores,
    assert_posture,
    assert_projection,
    assert_reserved_capacity,
    assert_runbook_state,
    factories as f,
    fixtures as fx,
    make_resilience_coordinator_headers,
    make_risk_approver_headers,
)


def test_only_the_platform_administrator_may_register_a_site(api):
    """The identical payload is refused for the coordinator and accepted for the admin.

    PRD: "A `PlatformAdmin` is the operational administrator: it registers and
    patches stakeholders, creates sites, drives the logical clock, and may also
    create applications and propose tiers." And: "If the headers are well formed but
    the declared role is not listed as an authorised role for the endpoint being
    called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/site_creation_by_a_coordinator_returns_unauthorized
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_PEOPLE_REGISTERED
    )
    payload = f.site_payload(
        site_code="SITE-X",
        name="Coordinator's own site",
        role="RECOVERY",
        usable_capacity_units=12,
    )

    validate_error(
        api.create_site(payload, estate["coordinator_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    site = validate_success(api.create_site(payload, PLATFORM_ADMIN_HEADERS), 201)

    assert site["site_code"] == "SITE-X"
    assert_reserved_capacity(site, 0)
    _, meta = validate_paginated(api.list_sites(PLATFORM_ADMIN_HEADERS))
    assert meta["total_count"] == 1


def test_three_different_roles_may_each_raise_a_finding(api):
    """Coordinator, operator and audit liaison all reach the same shared endpoint.

    PRD: "It shares application creation with `PlatformAdmin`, asset creation with
    `ITOperator`, runbook-step creation and step-execution recording with
    `ITOperator`, finding creation with `ITOperator` and `AuditLiaison`, and posture
    refresh with `AuditLiaison`." And: "A new finding starts in `state` `OPEN` with
    `owner_id` null, `retest_exercise_id` null, `retest_failure_count` 0 and
    `escalated` false, and raising it recomputes the group's `open_finding_count`,
    which rises by 1."

    Design: Corner/rbac/finding_creation_is_shared_across_three_roles
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_GROUP_CREATED)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
        name="Shared raise subject",
    )

    by_coordinator = fx.raise_finding(
        api,
        coordinator,
        exercise["id"],
        group_id,
        severity="HIGH",
        title="Raised by the coordinator",
        description="Runbook step ordering was wrong.",
    )
    by_operator = fx.raise_finding(
        api,
        estate["operator_headers"],
        exercise["id"],
        group_id,
        severity="MEDIUM",
        title="Raised by the operator",
        description="Console bookmark pointed at the old host.",
    )
    by_liaison = fx.raise_finding(
        api,
        estate["liaison_headers"],
        exercise["id"],
        group_id,
        severity="HIGH",
        title="Raised by the audit liaison",
        description="Evidence timestamps were not captured.",
    )

    for finding in (by_coordinator, by_operator, by_liaison):
        assert_finding_state(finding, "OPEN")
        assert finding["retest_failure_count"] == 0
        assert finding["escalated"] is False
    group = fx.read_group(api, coordinator, group_id)
    assert group["open_finding_count"] == 3
    assert_posture(group, "RESTRICTED", "NO_VALIDATED_RUNBOOK")
    _, meta = validate_paginated(
        api.list_findings(coordinator, params={"exercise_id": exercise["id"]})
    )
    assert meta["total_count"] == 3


def test_a_dual_hatted_coordinator_may_not_approve_their_own_exercise(api):
    """Ample authority does not survive the segregation check above it.

    PRD: "The stakeholder deciding an exercise's production impact — approving or
    rejecting — must not be the exercise's `coordinator_id`. Violations yield
    `ERR_SOD_IMPACT_APPROVER` (HTTP 422)." And: "Segregation of duties on the impact
    decision — `ERR_SOD_IMPACT_APPROVER` (422), on impact decisions, for both
    `APPROVE` and `REJECT`." And: "The approver's authority level is sufficient —
    `ERR_INSUFFICIENT_APPROVAL_AUTHORITY` (403), on an impact decision whose
    `action` is `APPROVE`."

    Design: Corner/rbac/dual_hatted_coordinator_cannot_approve_their_own_exercise
    """
    estate = fx.setup_single_application_estate(api)
    dual_hatted = fx.register_stakeholder(
        api,
        full_name="Ellis Kaur",
        email="ellis.kaur@example.com",
        org_roles=["RESILIENCE_COORDINATOR", "RISK_APPROVER"],
        approval_authority_level="LEVEL_3",
    )
    as_coordinator = make_resilience_coordinator_headers(dual_hatted["id"])
    exercise = fx.create_exercise(
        api,
        as_coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=dual_hatted["id"],
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
        name="Self-approval probe",
    )
    fx.scope_group(api, as_coordinator, exercise["id"], estate["group"]["id"])
    submitted = fx.submit_impact(api, as_coordinator, exercise["id"])
    assert_impact_scores(submitted, 30.50, 31.50, "LEVEL_1")

    validate_error(
        api.decide_impact(
            exercise["id"],
            f.impact_decision_payload("APPROVE", "Approving the exercise I coordinate"),
            make_risk_approver_headers(dual_hatted["id"]),
        ),
        ApiErrorId.ERR_SOD_IMPACT_APPROVER,
        422,
    )
    assert_axes(
        fx.read_exercise(api, as_coordinator, exercise["id"]),
        execution_state="PENDING_IMPACT_APPROVAL",
    )

    approved = fx.approve_impact(
        api, estate["approver_headers"], exercise["id"], note="Independent approval"
    )

    assert_axes(approved, execution_state="APPROVED")
    assert approved["impact_approved_by_id"] == estate["risk_approver"]["id"]


def test_neither_half_of_the_approval_chain_can_reach_into_the_other(api):
    """Scheduling is the coordinator's act and the decision is the approver's.

    PRD: "This role exclusively creates recovery groups and dependency edges,
    assigns applications and assets to groups, opens runbook revisions and drives
    runbook transitions, proposes application tiers, creates exercises, adds scope
    items, submits production impact, schedules exercises, drives execution
    transitions and drives finding transitions." And: "A `RiskApprover` then
    decides, supplying an `action` of `APPROVE` or `REJECT` with an optional
    `decision_note`." And: "The acting role is authorised for the endpoint —
    `ERR_UNAUTHORIZED` (403), on every endpoint."

    Design: Corner/rbac/risk_approver_cannot_schedule_and_coordinator_cannot_approve
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Chain probe",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    fx.submit_impact(api, coordinator, exercise["id"])

    validate_error(
        api.schedule_exercise(
            exercise["id"],
            {"scheduling_note": "Approver trying to book the window"},
            estate["approver_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.decide_impact(
            exercise["id"],
            f.impact_decision_payload("APPROVE", "Coordinator trying to approve"),
            coordinator,
        ),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    unchanged = fx.read_exercise(api, coordinator, exercise["id"])
    assert_axes(unchanged, execution_state="PENDING_IMPACT_APPROVAL")
    assert unchanged["impact_approved_by_id"] is None
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 0
    )


def test_the_group_version_that_just_worked_is_stale_on_the_next_publish(api):
    """Publishing bumps the parent, so the token must be re-read between writes.

    PRD: "If `expected_recovery_group_version` does not equal the group's current
    `version`, the create is rejected with `ERR_STALE_RECOVERY_GROUP_VERSION` (HTTP
    412)." And: "The server computes the new row's `revision` as one more than the
    number of runbooks that already exist on the same recovery group, counted in
    ascending `created_at` order, so the first revision is 1." And: "The new
    revision starts with `status` `DRAFT`, `readiness_score` 0.00, `stale_reason`
    `NONE` and `validated_at` null, and opening it increments the owning group's
    `version` by 1."

    Design: Corner/complexity_layers/runbook_publish_occ_accepts_the_observed_group_version_and_rejects_the_reused_one
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_GROUP_CREATED)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    first_version = fx.read_group(api, coordinator, group_id)["version"]
    assert first_version == 1

    first = validate_success(
        api.create_runbook(
            f.runbook_payload(
                group_id,
                estate["coordinator"]["id"],
                first_version,
                title="OCC revision one",
            ),
            coordinator,
        ),
        201,
    )
    second_version = fx.read_group(api, coordinator, group_id)["version"]
    assert second_version == 2
    validate_error(
        api.create_runbook(
            f.runbook_payload(
                group_id,
                estate["coordinator"]["id"],
                first_version,
                title="OCC revision two, stale writer",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_STALE_RECOVERY_GROUP_VERSION,
        412,
    )
    second = validate_success(
        api.create_runbook(
            f.runbook_payload(
                group_id,
                estate["coordinator"]["id"],
                second_version,
                title="OCC revision two, fresh writer",
            ),
            coordinator,
        ),
        201,
    )

    assert first["revision"] == 1
    assert first["validity_days"] == DEFAULT_VALIDITY_DAYS
    assert_runbook_state(first, "DRAFT", stale_reason="NONE", readiness_score=0.00)
    assert second["revision"] == 2
    group = fx.read_group(api, coordinator, group_id)
    assert group["version"] == 3
    assert group["current_runbook_id"] is None


def test_the_projection_is_a_full_recompute_rather_than_a_running_delta(api):
    """An isolated member loses, wiring it in wins, and a refresh changes nothing.

    PRD: "Over that directed subgraph — always acyclic, because cycle creation is
    blocked at write time — the server finds the directed path whose total node
    weight is greatest, and `projected_recovery_minutes` is that total." And: "A
    single node with no edges is itself a path of length one, so an isolated
    member's own weight is a candidate; a group with no members at all projects 0."
    And: "The projection is refreshed whenever the graph or the weights change: on
    assigning an application to a group, on assigning an asset to a group, on
    accepting a `HARD` dependency edge, on a business owner's agreement of a tier,
    and on an explicit posture refresh."

    Design: Corner/complexity_layers/projection_is_recomputed_from_scratch_on_every_membership_change
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_EDGE_CREATED)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    core_id = estate["app_core"]["id"]
    asset_id = estate["asset_db"]["id"]
    edge_app = fx.register_application(
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
        edge_app["id"],
        proposed_tier="TIER_2",
        proposed_rto_minutes=45,
        proposed_rpo_minutes=60,
    )

    fx.assign_application(api, coordinator, edge_app["id"], group_id)
    assert_projection(
        fx.read_group(api, coordinator, group_id), 80, [core_id, asset_id]
    )

    fx.create_dependency_edge(
        api,
        coordinator,
        from_node_kind="APPLICATION",
        from_node_id=edge_app["id"],
        to_node_kind="APPLICATION",
        to_node_id=core_id,
        edge_kind="HARD",
    )
    wired = fx.read_group(api, coordinator, group_id)
    assert_projection(wired, 125, [edge_app["id"], core_id, asset_id])
    assert_posture(wired, "RESTRICTED", "NO_VALIDATED_RUNBOOK")

    refreshed = validate_success(
        api.refresh_posture(group_id, estate["liaison_headers"]), 200
    )

    assert_projection(refreshed, 125, [edge_app["id"], core_id, asset_id])
    assert_posture(refreshed, "RESTRICTED", "NO_VALIDATED_RUNBOOK")
