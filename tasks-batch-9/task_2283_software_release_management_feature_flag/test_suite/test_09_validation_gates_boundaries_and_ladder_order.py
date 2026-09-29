"""Refusals and their satisfiable counterparts: blackouts, freezes, budgets, seals."""

from test_helpers import (
    ApiErrorId,
    ApprovalKind,
    ChangeState,
    CleanupState,
    DeliveryState,
    ReleasePhase,
    RiskClass,
    assert_instant,
    assert_stale_debt,
    assert_sweep_summary,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import RELEASE_FREEZE_AT
from test_helpers.factories import (
    make_approval_payload,
    make_rollout_step_payload,
)
from test_helpers.fixtures import (
    create_release,
    create_train,
    grant_freeze_exception,
    merge_change,
    plan_step,
    read_change,
    read_environment,
    read_deployment,
    read_flag,
    read_release,
    read_train,
    record_approval,
    reset_clock,
    scenario_approved_low_change_at_the_freeze_boundary,
    scenario_blackout_environment_with_two_reserved_windows,
    scenario_high_change_with_one_technical_approval,
    scenario_high_change_without_a_rollback_plan,
    scenario_stale_and_fresh_flags_after_one_sweep,
    scenario_tight_budget_train_with_one_approved_medium,
    scenario_two_stabilizing_releases_regulated_and_open,
    set_clock,
    start_deployment,
)
from test_helpers.test_users import (
    CHANGE_APPROVER,
    ENGINEER,
    RELEASE_MANAGER,
    SECOND_CHANGE_APPROVER,
    SRE,
)

#: One second before the release's freeze instant.
JUST_BEFORE_FREEZE_AT = "2026-08-07T23:59:59Z"

#: An instant inside the blackout interval and inside the early window.
INSIDE_BLACKOUT_AT = "2026-08-10T02:05:00Z"

#: An instant after the closed blackout interval and inside the late window.
AFTER_BLACKOUT_AT = "2026-08-10T05:05:00Z"

#: The instant the unregulated release's production deployment was started.
UNREGULATED_START_AT = "2026-08-11T02:05:00Z"


class TestDeploymentBlackoutGate:
    """"This rank guards deployment start"."""

    def test_a_start_inside_the_closed_blackout_is_refused_while_the_later_one_runs(
        self, api
    ):
        """"the clock must not lie inside the environment's closed blackout span from
        ``blackout_start_at`` to ``blackout_end_at``", an interval whose "both
        endpoints are inside the blackout".

        Design: Corner/validations/start_deployment_inside_environment_blackout_returns_blackout_active
        """
        built = scenario_blackout_environment_with_two_reserved_windows(api)
        assert built["early"]["delivery_state"] == DeliveryState.SCHEDULED
        assert built["late"]["delivery_state"] == DeliveryState.SCHEDULED
        set_clock(api, INSIDE_BLACKOUT_AT)

        refused = api.start_deployment(built["early"]["id"], {}, SRE)
        started = start_deployment(api, built["late"]["id"], AFTER_BLACKOUT_AT)

        validate_error(refused, ApiErrorId.ERR_BLACKOUT_ACTIVE.value, 409)
        held = read_deployment(api, built["early"]["id"])
        assert held["delivery_state"] == DeliveryState.SCHEDULED
        assert started["delivery_state"] == DeliveryState.IN_PROGRESS
        environment = read_environment(api, built["environment"]["id"])
        assert environment["active_deployment_count"] == 1
        assert read_release(api, built["release"]["id"])["phase"] == (
            ReleasePhase.STABILIZING
        )


class TestApprovalLaneUniqueness:
    """A lane is a slot on the change, not a signature from a person."""

    def test_a_second_technical_approval_by_another_approver_is_refused(self, api):
        """"recording the same lane a second time with decision ``APPROVE`` is refused
        with ``ERR_DUPLICATE_APPROVAL_KIND``".

        Design: Corner/validations/duplicate_technical_approval_returns_duplicate_approval_kind
        """
        built = scenario_high_change_with_one_technical_approval(api)
        change_id = built["change"]["id"]
        assert built["submitted"]["risk_score_preliminary"] == 62
        assert built["submitted"]["risk_class"] == RiskClass.HIGH

        refused = api.create_approval(
            change_id,
            make_approval_payload(kind=ApprovalKind.TECHNICAL),
            SECOND_CHANGE_APPROVER,
        )

        validate_error(refused, ApiErrorId.ERR_DUPLICATE_APPROVAL_KIND.value, 409)
        change = read_change(api, change_id)
        assert change["approval_technical_count"] == 1
        assert change["approval_compliance_count"] == 0
        assert change["state"] == ChangeState.RISK_CLASSIFIED
        _, meta = validate_paginated(api.list_approvals(change_id, CHANGE_APPROVER))
        assert meta["total_count"] == 1
        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 0
        assert release["committed_change_count"] == 0


class TestCleanupEnforcementBlocksNewRungs:
    """"Enforcement is a wall, not a fine"."""

    def test_the_enforced_flag_takes_no_new_rung_while_its_compliant_sibling_does(
        self, api
    ):
        """"While a flag's ``cleanup_state`` is ``ENFORCED``, three operations are
        refused with ``ERR_FLAG_CLEANUP_ENFORCED``: resuming the flag, starting a
        soak on any of its steps, and planning a new rung".

        Design: Corner/validations/create_rollout_step_on_enforced_stale_flag_returns_flag_cleanup_enforced
        """
        built = scenario_stale_and_fresh_flags_after_one_sweep(api)
        assert_sweep_summary(built["sweep"], evaluated_count=2, enforced_count=1)
        assert_stale_debt(built["stale"], 60, CleanupState.ENFORCED)
        # The fresh flag has no change-to-flag links either, so it carries the
        # fifteen orphan points on its own and lands in WARNING, not COMPLIANT.
        assert_stale_debt(built["fresh"], 15, CleanupState.WARNING)

        refused = api.create_rollout_step(
            built["stale"]["id"],
            make_rollout_step_payload(
                built["stale"]["version"], target_pct=5, soak_minutes=30
            ),
            ENGINEER,
        )
        allowed = plan_step(api, built["fresh"]["id"], target_pct=5, soak_minutes=30)

        validate_error(refused, ApiErrorId.ERR_FLAG_CLEANUP_ENFORCED.value, 409)
        assert allowed["step_index"] == 1
        _, meta = validate_paginated(
            api.list_rollout_steps(ENGINEER, {"feature_flag_id": built["stale"]["id"]})
        )
        assert meta["total_count"] == 0
        assert read_flag(api, built["stale"]["id"])["cleanup_state"] == (
            CleanupState.ENFORCED
        )


class TestFreezeExceptionOpensTheGate:
    """"Code freeze can be overridden, but only by compliance"."""

    def test_the_merge_refused_at_the_freeze_instant_succeeds_after_the_exception(
        self, api
    ):
        """"the logical clock must still be strictly before the release's
        ``freeze_at``, unless ``freeze_exception_approved`` is true", and that flag
        "is what allows a merge to proceed past ``freeze_at``".

        Design: Corner/validations/merge_after_freeze_at_passes_once_freeze_exception_is_approved
        """
        built = scenario_approved_low_change_at_the_freeze_boundary(api)
        change_id = built["change"]["id"]
        assert built["change"]["state"] == ChangeState.APPROVED
        assert built["change"]["risk_score_final"] == 9

        refused = api.merge_change_request(change_id, {}, ENGINEER)
        excepted = grant_freeze_exception(api, built["release"]["id"])
        merged = merge_change(api, change_id)

        validate_error(refused, ApiErrorId.ERR_CODE_FREEZE_ACTIVE.value, 409)
        assert excepted["freeze_exception_approved"] is True
        assert read_train(api, built["train"]["id"])["freeze_exception_count"] == 1
        assert merged["state"] == ChangeState.MERGED
        assert_instant(merged["merged_at"], RELEASE_FREEZE_AT, "merged_at")
        release = read_release(api, built["release"]["id"])
        assert release["committed_change_count"] == 1
        assert release["risk_budget_consumed_points"] == 9


class TestCutBoundaryIsInclusive:
    """"reaching it exactly is sufficient"."""

    def test_the_cut_is_refused_until_the_freeze_instant_arrives_exactly(self, api):
        """"The logical clock must have reached the release's ``freeze_at``, where
        reaching it exactly is sufficient; an earlier attempt is refused with
        ``ERR_CUT_BEFORE_FREEZE``".

        Design: Corner/validations/cut_before_freeze_at_rejected_up_to_the_inclusive_boundary
        """
        reset_clock(api)
        train = create_train(api)
        release = create_release(api, train["id"])
        assert_instant(release["freeze_at"], RELEASE_FREEZE_AT, "freeze_at")

        too_early = api.cut_release(release["id"], {}, RELEASE_MANAGER)
        set_clock(api, JUST_BEFORE_FREEZE_AT)
        one_second_short = api.cut_release(release["id"], {}, RELEASE_MANAGER)
        set_clock(api, RELEASE_FREEZE_AT)
        on_the_boundary = api.cut_release(release["id"], {}, RELEASE_MANAGER)

        validate_error(too_early, ApiErrorId.ERR_CUT_BEFORE_FREEZE.value, 409)
        validate_error(one_second_short, ApiErrorId.ERR_CUT_BEFORE_FREEZE.value, 409)
        cut = validate_success(on_the_boundary, 200)
        assert cut["phase"] == ReleasePhase.CUT
        assert cut["readiness_score_attested"] == 100
        assert read_train(api, train["id"])["open_release_count"] == 0


class TestTrainRiskBudgetCeiling:
    """"the whole approval is refused ... and nothing is recorded"."""

    def test_the_second_approval_that_would_breach_the_budget_records_nothing(self, api):
        """"If that addition would push ``risk_budget_consumed_points`` above the
        train's ``risk_budget_points``, the whole approval is refused with
        ``ERR_RISK_BUDGET_EXCEEDED`` and nothing is recorded".

        Design: Corner/validations/second_approval_crossing_train_risk_budget_returns_risk_budget_exceeded
        """
        built = scenario_tight_budget_train_with_one_approved_medium(api)
        second_id = built["second"]["id"]
        assert built["first"]["state"] == ChangeState.APPROVED
        assert built["first"]["risk_score_final"] == 33
        assert built["release"]["risk_budget_consumed_points"] == 33
        assert built["release"]["committed_change_count"] == 1

        refused = api.create_approval(
            second_id, make_approval_payload(kind=ApprovalKind.TECHNICAL), CHANGE_APPROVER
        )

        validate_error(refused, ApiErrorId.ERR_RISK_BUDGET_EXCEEDED.value, 409)
        second = read_change(api, second_id)
        assert second["state"] == ChangeState.RISK_CLASSIFIED
        assert second["approval_technical_count"] == 0
        assert second["risk_score_final"] is None
        _, meta = validate_paginated(api.list_approvals(second_id, CHANGE_APPROVER))
        assert meta["total_count"] == 0
        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 33
        assert release["committed_change_count"] == 1


class TestRegulatedEvidenceGate:
    """The seal is demanded by the environment, not by the release."""

    def test_only_the_release_that_landed_on_the_regulated_environment_needs_a_seal(
        self, api
    ):
        """"If that production environment's ``requires_compliance_evidence`` is true,
        the release must also have an evidence packet in ``state`` ``SEALED``, and a
        missing seal is refused with ``ERR_EVIDENCE_PACKET_REQUIRED``".

        Design: Corner/validations/release_requires_sealed_evidence_only_on_regulated_environment
        """
        built = scenario_two_stabilizing_releases_regulated_and_open(api)
        for release in (built["regulated"], built["unregulated"]):
            assert release["phase"] == ReleasePhase.STABILIZING
            assert release["readiness_score_attested"] == 100

        refused = api.ship_release(built["regulated"]["id"], {}, RELEASE_MANAGER)
        shipped = validate_success(
            api.ship_release(built["unregulated"]["id"], {}, RELEASE_MANAGER), 200
        )

        validate_error(refused, ApiErrorId.ERR_EVIDENCE_PACKET_REQUIRED.value, 409)
        held = read_release(api, built["regulated"]["id"])
        assert held["phase"] == ReleasePhase.STABILIZING
        assert held["released_at"] is None
        assert shipped["phase"] == ReleasePhase.RELEASED
        assert_instant(shipped["released_at"], UNREGULATED_START_AT, "released_at")
        assert shipped["verified_change_count"] == 1
        assert read_change(api, built["open_change"]["id"])["deployment_verified"] is True


class TestMergeLadderOrdering:
    """The six merge conditions "are checked in the ladder order of §2.8"."""

    def test_the_state_refusal_precedes_the_rollback_plan_refusal(self, api):
        """"Merging is the author's act, permitted only from ``state`` ``APPROVED``";
        only then does "its ``rollback_plan`` must be non-null and its
        ``rollback_tested`` must be true, or the merge is refused with
        ``ERR_ROLLBACK_PLAN_REQUIRED``" become reachable.

        Design: Corner/validations/merge_state_check_runs_before_the_rollback_plan_check
        """
        built = scenario_high_change_without_a_rollback_plan(api)
        change_id = built["change"]["id"]

        state_refusal = api.merge_change_request(change_id, {}, ENGINEER)
        record_approval(api, change_id, ApprovalKind.TECHNICAL)
        record_approval(api, change_id, ApprovalKind.COMPLIANCE)
        plan_refusal = api.merge_change_request(change_id, {}, ENGINEER)

        validate_error(state_refusal, ApiErrorId.ERR_CHANGE_STATE_INVALID.value, 409)
        validate_error(plan_refusal, ApiErrorId.ERR_ROLLBACK_PLAN_REQUIRED.value, 422)
        change = read_change(api, change_id)
        assert change["state"] == ChangeState.APPROVED
        assert change["risk_score_final"] == 62
        assert change["approval_technical_count"] == 1
        assert change["approval_compliance_count"] == 1
        assert change["merged_at"] is None
        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 62
        assert release["committed_change_count"] == 1
