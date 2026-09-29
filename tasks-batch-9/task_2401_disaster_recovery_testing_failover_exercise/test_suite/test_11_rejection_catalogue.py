"""Refusals from across the catalogue: headers, identity, authority, uniqueness and duty."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    PLATFORM_ADMIN_HEADERS,
    assert_achieved,
    assert_axes,
    assert_impact_scores,
    assert_objectives,
    assert_posture,
    assert_reserved_capacity,
    assert_runbook_state,
    assert_score,
    factories as f,
    fixtures as fx,
    make_audit_liaison_headers,
    make_business_owner_headers,
    make_resilience_coordinator_headers,
    make_risk_approver_headers,
)


def test_a_request_with_no_role_header_is_unauthenticated_before_any_body_check(api):
    """The header rule outranks the body rule, so the shape error is never reported.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting
    individual, and `X-User-Role`, declaring the operational capacity they are
    acting in." And: "If either header is absent, or if `X-User-Role` is not one of
    the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)." And: "When several checks could reject the same request, the server
    evaluates them in a fixed global order and reports the **first** failure only."

    Design: Corner/errors/missing_x_user_role_header_returns_unauthenticated
    """
    fx.set_logical_clock(api, CLOCK_EPOCH)

    validate_error(
        api.create_site({"name": "Header-less site"}, {}),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    _, meta = validate_paginated(api.list_sites(PLATFORM_ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_a_coordinator_header_over_an_audit_liaison_identity_is_a_mismatch(api):
    """The declared hat must be one the acting stakeholder actually wears.

    PRD: "For those five roles the server additionally requires that `X-User-ID`
    resolves to a `Stakeholder` whose `status` is `ACTIVE` and whose `org_roles`
    array contains the organisational hat that corresponds to the declared role:
    `BusinessOwner` maps to `BUSINESS_OWNER`, `ResilienceCoordinator` to
    `RESILIENCE_COORDINATOR`, `ITOperator` to `IT_OPERATOR`, `RiskApprover` to
    `RISK_APPROVER`, and `AuditLiaison` to `AUDIT_LIAISON`." And: "A mismatch —
    unknown id, `SUSPENDED` status, or a missing organisational hat — is rejected
    with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/errors/coordinator_header_with_an_audit_liaison_identity_rejected
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_SITES_REGISTERED
    )
    impostor_headers = make_resilience_coordinator_headers(
        estate["audit_liaison"]["id"]
    )

    validate_error(
        api.create_application(
            f.application_payload(
                business_owner_id=estate["business_owner"]["id"],
                primary_site_id=estate["site_primary"]["id"],
                app_code="APP-IMP",
                name="Impostor app",
                criticality_weight=3,
            ),
            impostor_headers,
        ),
        ApiErrorId.ERR_ROLE_IDENTITY_MISMATCH,
        403,
    )

    _, meta = validate_paginated(
        api.list_applications(estate["coordinator_headers"])
    )
    assert meta["total_count"] == 0


def test_a_level_two_approver_cannot_clear_a_level_three_exercise(api):
    """Authority is measured against the exercise's own derived requirement.

    PRD: "A `LEVEL_2` approver may therefore clear a `LEVEL_1` or `LEVEL_2` exercise
    but not a `LEVEL_3` one; the shortfall is reported as
    `ERR_INSUFFICIENT_APPROVAL_AUTHORITY` (HTTP 403)." And: "**The governance
    surcharge** is keyed on that *provisional* band: 1 for `LEVEL_1`, 3 for
    `LEVEL_2`, 5 for `LEVEL_3`." And: "**The required authority** is read off the
    *final* score with the same banding rule, and stored as
    `required_approval_level`."

    Design: Corner/errors/level_two_approver_on_a_level_three_exercise_rejected
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    mid_approver = fx.register_stakeholder(
        api,
        full_name="Ray Mid",
        email="ray.mid@example.com",
        org_roles=["RISK_APPROVER"],
        approval_authority_level="LEVEL_2",
    )
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
    exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Whole-site rehearsal",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T12:00:00Z",
        exercise_type="FULL_SITE_FAILOVER",
    )
    submitted = fx.submit_impact(api, coordinator, exercise["id"])
    assert submitted["required_capacity_units"] == 6
    assert_impact_scores(submitted, 59.50, 62.50, "LEVEL_3")

    validate_error(
        api.decide_impact(
            exercise["id"],
            f.impact_decision_payload("APPROVE", "Approving above my authority"),
            make_risk_approver_headers(mid_approver["id"]),
        ),
        ApiErrorId.ERR_INSUFFICIENT_APPROVAL_AUTHORITY,
        403,
    )
    assert_axes(
        fx.read_exercise(api, coordinator, exercise["id"]),
        execution_state="PENDING_IMPACT_APPROVAL",
    )

    approved = fx.approve_impact(
        api, estate["approver_headers"], exercise["id"], note="Level 3 sign-off"
    )

    assert_axes(approved, execution_state="APPROVED")
    assert approved["impact_approved_by_id"] == estate["risk_approver"]["id"]
    assert_reserved_capacity(
        fx.read_site(api, coordinator, estate["site_recovery"]["id"]), 0
    )


def test_a_duplicate_group_code_and_a_duplicate_step_number_are_both_refused(api):
    """One code is unique table-wide, the other only inside its own runbook.

    PRD: "A duplicate `group_code` yields `ERR_DUPLICATE_CODE`." And: "A repeated
    `step_number` inside the same runbook is rejected with
    `ERR_DUPLICATE_STEP_NUMBER`, and steps may not be added to a runbook whose
    `status` is `SUPERSEDED`, which is reported as `ERR_INVALID_STEP_STATE`."

    Design: Corner/errors/duplicate_group_code_and_duplicate_step_number_rejected
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_STEP_ADDED)
    coordinator = estate["coordinator_headers"]
    runbook_id = estate["runbook"]["id"]

    validate_error(
        api.create_recovery_group(
            f.recovery_group_payload(
                recovery_site_id=estate["site_recovery"]["id"],
                lead_coordinator_id=estate["coordinator"]["id"],
                group_code="RG-1",
                name="Copycat group",
                recovery_order=9,
            ),
            coordinator,
        ),
        ApiErrorId.ERR_DUPLICATE_CODE,
        409,
    )
    validate_error(
        api.create_runbook_step(
            f.runbook_step_payload(
                runbook_id=runbook_id,
                owner_id=estate["operator"]["id"],
                step_number=1,
                description="Second step numbered one",
                expected_minutes=5,
                weight=10,
            ),
            coordinator,
        ),
        ApiErrorId.ERR_DUPLICATE_STEP_NUMBER,
        409,
    )

    _, group_meta = validate_paginated(api.list_recovery_groups(coordinator))
    assert group_meta["total_count"] == 1
    _, step_meta = validate_paginated(
        api.list_runbook_steps(coordinator, params={"runbook_id": runbook_id})
    )
    assert step_meta["total_count"] == 1
    assert_runbook_state(
        fx.read_runbook(api, coordinator, runbook_id), "DRAFT", readiness_score=0.00
    )


def test_the_same_pair_may_be_re_added_only_under_the_other_edge_kind(api):
    """Uniqueness keys on the triple, and the soft twin changes no projection.

    PRD: "No existing edge already has the same `from_node_id`, `to_node_id` and
    `edge_kind` — `ERR_DUPLICATE_DEPENDENCY_EDGE` (409), on dependency-edge
    creation." And: "The edge set is every `HARD` dependency edge whose two
    endpoints are both members of that node set; `SOFT` edges are excluded, and
    every edge that reaches outside the group's membership is excluded too."

    Design: Corner/errors/duplicate_dependency_edge_rejected_while_the_other_kind_is_accepted
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_EDGE_CREATED)
    coordinator = estate["coordinator_headers"]
    application_id = estate["app_core"]["id"]
    asset_id = estate["asset_db"]["id"]

    validate_error(
        api.create_dependency_edge(
            f.dependency_edge_payload(
                "APPLICATION", application_id, "ASSET", asset_id, "HARD"
            ),
            coordinator,
        ),
        ApiErrorId.ERR_DUPLICATE_DEPENDENCY_EDGE,
        409,
    )
    soft_edge = validate_success(
        api.create_dependency_edge(
            f.dependency_edge_payload(
                "APPLICATION", application_id, "ASSET", asset_id, "SOFT"
            ),
            coordinator,
        ),
        201,
    )

    assert soft_edge["edge_kind"] == "SOFT"
    _, meta = validate_paginated(
        api.list_dependency_edges(coordinator, params={"from_node_id": application_id})
    )
    assert meta["total_count"] == 2
    assert fx.read_group(api, coordinator, estate["group"]["id"])[
        "projected_recovery_minutes"
    ] == 80


def test_a_step_execution_clears_the_scope_gate_before_the_duty_gate(api):
    """Only the third attempt — in scope and not by the owner — is stored.

    PRD: "The cited step must belong to the runbook revision one of this exercise's
    scope items snapshotted as `runbook_id_snapshot`; timing a step from some other
    revision, or from a group that was never in scope, is rejected with
    `ERR_STEP_NOT_IN_SCOPE`." And: "The stakeholder recording a step execution must
    not be the `owner_id` of the runbook step being timed. Violations yield
    `ERR_SOD_STEP_OWNER` (HTTP 422)." And: "`elapsed_seconds` may not be negative,
    and the server derives `elapsed_minutes` from it at write time by rounding *up*
    to a whole minute — a 61-second step is pinned at 2 minutes and stays pinned."

    Design: Corner/errors/step_execution_out_of_scope_and_by_the_step_owner_rejected
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
        name="Scope and duty probe",
    )
    scope_item = fx.scope_group(api, coordinator, exercise["id"], estate["group"]["id"])
    fx.submit_impact(api, coordinator, exercise["id"])
    fx.approve_impact(api, estate["approver_headers"], exercise["id"])
    fx.schedule(api, coordinator, exercise["id"])
    fx.drive_execution(api, coordinator, exercise["id"], "START")
    unpublished = fx.open_runbook(
        api,
        coordinator,
        estate["group"]["id"],
        estate["coordinator"]["id"],
        title="Draft revision not yet published",
    )
    outside_step = fx.add_step(
        api,
        coordinator,
        unpublished["id"],
        estate["operator"]["id"],
        step_number=1,
        description="Step of an unpublished revision",
        expected_minutes=9,
        weight=10,
    )
    assert scope_item["runbook_id_snapshot"] == estate["runbook"]["id"]

    validate_error(
        api.create_step_execution(
            exercise["id"],
            f.step_execution_payload(outside_step["id"], "PASSED", 300),
            coordinator,
        ),
        ApiErrorId.ERR_STEP_NOT_IN_SCOPE,
        422,
    )
    validate_error(
        api.create_step_execution(
            exercise["id"],
            f.step_execution_payload(estate["step_core"]["id"], "PASSED", 300),
            estate["operator_headers"],
        ),
        ApiErrorId.ERR_SOD_STEP_OWNER,
        422,
    )
    recorded = validate_success(
        api.create_step_execution(
            exercise["id"],
            f.step_execution_payload(
                estate["step_core"]["id"],
                "PASSED_WITH_ISSUE",
                300,
                notes="Recorded by the coordinator, not the owner",
            ),
            coordinator,
        ),
        201,
    )

    assert recorded["outcome"] == "PASSED_WITH_ISSUE"
    assert recorded["elapsed_minutes"] == 5
    assert recorded["performed_by_user_id"] == estate["coordinator"]["id"]
    _, meta = validate_paginated(
        api.list_step_executions(coordinator, params={"exercise_id": exercise["id"]})
    )
    assert meta["total_count"] == 1


def test_the_proposer_is_stopped_before_ownership_is_ever_considered(api):
    """Two would-be agreements fail for two different reasons at two ranks.

    PRD: "The stakeholder agreeing an application's tier must not be the stakeholder
    recorded in `proposed_by_id` on that application. A self-agreed proposal is
    rejected with `ERR_SOD_TIER_PROPOSER` (HTTP 422)." And: "Holding the
    `BUSINESS_OWNER` organisational hat is not sufficient to decide somebody else's
    application, and the mismatch is reported as `ERR_NOT_APPLICATION_OWNER` (HTTP
    403)." And: "This check sits deliberately at the very bottom of the ladder: an
    application in the wrong tier state reports its state error at rank 13, and a
    self-agreed proposal reports its segregation-of-duties error at rank 17, both
    before ownership is ever considered."

    Design: Corner/errors/tier_agreed_by_its_proposer_and_by_a_foreign_owner_rejected
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_SITES_REGISTERED
    )
    dual_hatted = fx.register_stakeholder(
        api,
        full_name="Dora Vey",
        email="dora.vey@example.com",
        org_roles=["RESILIENCE_COORDINATOR", "BUSINESS_OWNER"],
        approval_authority_level="LEVEL_1",
    )
    application = fx.register_application(
        api,
        make_resilience_coordinator_headers(dual_hatted["id"]),
        business_owner_id=dual_hatted["id"],
        primary_site_id=estate["site_primary"]["id"],
        app_code="APP-SOD",
        name="Self-agreement probe",
        criticality_weight=5,
    )
    proposed = validate_success(
        api.propose_application_tier(
            application["id"],
            f.tier_proposal_payload("TIER_2", 120, 30, "Proposed by the owner herself"),
            make_resilience_coordinator_headers(dual_hatted["id"]),
        ),
        201,
    )
    assert proposed["proposed_by_id"] == dual_hatted["id"]
    assert proposed["business_owner_id"] == dual_hatted["id"]

    validate_error(
        api.decide_application_tier(
            application["id"],
            f.tier_decision_payload("AGREE", "Agreeing to my own proposal"),
            make_business_owner_headers(dual_hatted["id"]),
        ),
        ApiErrorId.ERR_SOD_TIER_PROPOSER,
        422,
    )
    validate_error(
        api.decide_application_tier(
            application["id"],
            f.tier_decision_payload("AGREE", "Agreeing to somebody else's application"),
            estate["owner_headers"],
        ),
        ApiErrorId.ERR_NOT_APPLICATION_OWNER,
        403,
    )

    stored = validate_success(
        api.get_application(application["id"], estate["coordinator_headers"])
    )
    assert stored["tier_agreement_status"] == "TIER_PROPOSED"
    assert stored["rto_minutes"] is None
    assert stored["rpo_minutes"] is None


def test_the_two_interval_rules_use_different_comparators(api):
    """An equal exercise window fails, while a missing group answers before any window.

    PRD: "Interval sanity: `planned_end_at` is strictly after `planned_start_at`,
    and `change_freeze_end_at` is at or after `change_freeze_start_at` —
    `ERR_INVALID_WINDOW` (422), on exercise creation and on setting a group's change
    freeze." And: "Existence of every id templated into the path, validated **left
    to right**, on every endpoint with a templated segment."

    Design: Corner/errors/zero_length_exercise_window_and_unknown_group_rejected
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_SITES_REGISTERED
    )
    coordinator = estate["coordinator_headers"]

    validate_error(
        api.create_exercise(
            f.exercise_payload(
                recovery_site_id=estate["site_recovery"]["id"],
                coordinator_id=estate["coordinator"]["id"],
                planned_start_at="2026-08-20T00:00:00Z",
                planned_end_at="2026-08-20T00:00:00Z",
                name="Zero-length window",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_WINDOW,
        422,
    )
    validate_error(
        api.set_change_freeze(
            NON_EXISTENT_UUID,
            f.change_freeze_payload("2026-09-01T00:00:00Z", "2026-08-01T00:00:00Z"),
            coordinator,
        ),
        ApiErrorId.ERR_RECOVERY_GROUP_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(api.list_exercises(coordinator))
    assert meta["total_count"] == 0


def test_a_short_validity_expires_while_the_readiness_floor_still_holds(api):
    """Two independent scoping gates: the floor passes and the validity does not.

    PRD: "The runbook being snapshotted must still be inside its validity period."
    And: "Take the elapsed time from that runbook's `validated_at` to the current
    logical clock, divide by 86400 seconds and discard the fraction to get whole
    days; that figure must be at most the runbook's `validity_days`." And: "A
    runbook validated longer ago than its declared validity is rejected with
    `ERR_RUNBOOK_VALIDITY_EXPIRED`."

    Design: Corner/errors/runbook_past_its_validity_days_rejects_scoping_while_readiness_still_passes
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_GROUP_VERSION_READ
    )
    coordinator = estate["coordinator_headers"]
    runbook = fx.open_runbook(
        api,
        coordinator,
        estate["group"]["id"],
        estate["coordinator"]["id"],
        title="Short-validity runbook",
        validity_days=30,
    )
    step = fx.add_step(
        api,
        coordinator,
        runbook["id"],
        estate["operator"]["id"],
        step_number=1,
        description="Promote the ledger replica",
        expected_minutes=15,
        weight=10,
        covers_application_id=estate["app_core"]["id"],
    )
    fx.transition_runbook(api, coordinator, runbook["id"], "SUBMIT_FOR_REVIEW")
    fx.validate_step(api, estate["operator_headers"], step["id"])
    fx.transition_runbook(api, coordinator, runbook["id"], "VALIDATE")
    fx.set_logical_clock(api, "2026-09-10T00:00:00Z")
    exercise = fx.create_exercise(
        api,
        coordinator,
        recovery_site_id=estate["site_recovery"]["id"],
        coordinator_id=estate["coordinator"]["id"],
        planned_start_at="2026-09-20T00:00:00Z",
        planned_end_at="2026-09-20T06:00:00Z",
        name="Late scoping attempt",
    )

    validate_error(
        api.create_scope_item(
            exercise["id"],
            f.scope_item_payload(estate["group"]["id"], exercise["version"]),
            coordinator,
        ),
        ApiErrorId.ERR_RUNBOOK_VALIDITY_EXPIRED,
        422,
    )

    assert_score(
        fx.read_runbook(api, coordinator, runbook["id"])["readiness_score"], 88.89
    )
    assert_posture(
        fx.read_group(api, coordinator, estate["group"]["id"]),
        "READY",
        "READY_ALL_CHECKS_PASSED",
    )
    still_draft = fx.read_exercise(api, coordinator, exercise["id"])
    assert_axes(still_draft, execution_state="DRAFT")
    assert still_draft["required_capacity_units"] == 0
    assert still_draft["version"] == 1
    _, meta = validate_paginated(
        api.list_scope_items(coordinator, params={"exercise_id": exercise["id"]})
    )
    assert meta["total_count"] == 0


def test_the_preparer_of_an_evidence_package_may_not_sign_it_off(api):
    """Wearing the approver's hat too does not let the preparer bless their own work.

    PRD: "The stakeholder signing off an evidence package must not be its
    `prepared_by_id`. Violations yield `ERR_SOD_EVIDENCE_SIGNER` (HTTP 422)." And:
    "which is precisely why the segregation-of-duties rules in §2.6 are enforced on
    identity rather than on role." And:
    "`SIGN_OFF` belongs to the `RiskApprover` and moves `SUBMITTED` to
    `SIGNED_OFF`, recording the approver's `X-User-ID` in `signed_off_by_id`." And:
    "For a `TABLETOP` or a `COMPONENT_FAILOVER` the measure is *net hands-on time*:
    add up the `elapsed_minutes` of every step execution of this exercise whose
    `outcome` is `PASSED`, `PASSED_WITH_ISSUE` or `FAILED`." And: "Under replication
    lag, each data store yields its chosen observation's `replication_lag_seconds`
    converted to whole minutes by rounding up, and `achieved_rpo_minutes` is the
    largest of those per-asset figures."

    Design: Corner/errors/evidence_sign_off_by_its_preparer_rejected
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    # One person wearing both hats: they assemble the package as the liaison and
    # then attempt to sign their own work while acting as a risk approver.
    dual_hat = fx.register_stakeholder(
        api,
        full_name="Dana Reyes",
        email="dana.reyes@example.com",
        org_roles=["AUDIT_LIAISON", "RISK_APPROVER"],
        approval_authority_level="LEVEL_1",
    )
    liaison = make_audit_liaison_headers(dual_hat["id"])
    liaison_as_approver = make_risk_approver_headers(dual_hat["id"])
    exercise = fx.setup_exercise_at_failover_complete(
        api,
        estate,
        elapsed_seconds=780,
        name="Sign-off subject",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )
    fx.drive_both_axes_to_terminal(api, estate["operator_headers"], exercise["id"])
    fx.drive_execution(api, coordinator, exercise["id"], "CLOSE")
    package = fx.open_evidence_package(
        api, liaison, exercise["id"], dual_hat["id"]
    )
    fx.transition_evidence(api, liaison, package["id"], "SUBMIT")

    validate_error(
        api.transition_evidence_package(
            package["id"],
            f.evidence_transition_payload("SIGN_OFF", "Signing my own package"),
            liaison_as_approver,
        ),
        ApiErrorId.ERR_SOD_EVIDENCE_SIGNER,
        422,
    )
    still_submitted = fx.read_evidence_package(api, liaison, package["id"])
    assert still_submitted["state"] == "SUBMITTED"
    assert still_submitted["signed_off_by_id"] is None

    signed = fx.transition_evidence(
        api,
        estate["approver_headers"],
        package["id"],
        "SIGN_OFF",
        note="Independent risk sign-off",
    )

    assert signed["state"] == "SIGNED_OFF"
    assert signed["signed_off_by_id"] == estate["risk_approver"]["id"]
    assert signed["manifest_line_count"] == 3
    assert signed["sealed_at"] is None
    closed = fx.read_exercise(api, coordinator, exercise["id"])
    assert_objectives(closed, 60, 15)
    assert_achieved(
        closed,
        achieved_rto_minutes=13,
        achieved_rpo_minutes=4,
        rto_met=True,
        rpo_met=True,
    )
