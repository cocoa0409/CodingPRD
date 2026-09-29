"""Readiness variants, ledger compensation, and the stabilization capacity gate."""

from test_helpers import (
    ApiErrorId,
    ChangeState,
    ReleasePhase,
    TrainPhase,
    assert_instant,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    freeze_train,
    read_change,
    read_release,
    read_train,
    scenario_release_ready_to_cut_with_deferrable_change,
    scenario_three_releases_contending_for_one_slot,
    scenario_train_with_approved_dependent_before_freeze,
    scenario_two_approved_changes_with_dependency,
    withdraw_change,
)
from test_helpers.test_users import RELEASE_MANAGER


class TestProjectedAndAttestedReadiness:
    """The two readiness figures "answer different questions"."""

    def test_projected_score_assumes_everything_still_alive_will_land(self, api):
        """The projected figure "is forward-looking: it assumes everything still
        alive will land", and "unapproved-but-live work attracts no not-landed
        penalty at all".

        Design: Difficulty/dual_variant_calc/release_readiness_projected_vs_attested_diverge_on_deferred_change
        """
        built = scenario_release_ready_to_cut_with_deferrable_change(api)

        assert built["projected_before_cut"] == 100

    def test_cut_pins_an_attested_score_that_penalises_the_unlanded_change(self, api):
        """The attested figure "is chronological: it judges what actually landed by
        the freeze deadline", subtracting "six times the number of unlanded
        changes".

        Design: Difficulty/dual_variant_calc/release_readiness_projected_vs_attested_diverge_on_deferred_change
        """
        built = scenario_release_ready_to_cut_with_deferrable_change(api)

        cut = validate_success(api.cut_release(built["release"]["id"], {}, RELEASE_MANAGER))

        assert cut["readiness_score_attested"] == 94
        assert cut["readiness_score_projected"] == 100
        assert cut["readiness_score_projected"] != cut["readiness_score_attested"]

    def test_cut_defers_the_in_flight_change_before_computing_the_attested_score(
        self, api
    ):
        """"this deferral is pinned to run *before* the attested score is computed,
        so those changes are counted in their post-deferral state".

        Design: Difficulty/dual_variant_calc/release_readiness_projected_vs_attested_diverge_on_deferred_change
        """
        built = scenario_release_ready_to_cut_with_deferrable_change(api)

        validate_success(api.cut_release(built["release"]["id"], {}, RELEASE_MANAGER))

        assert read_change(api, built["change_medium"]["id"])["state"] == (
            ChangeState.DEFERRED
        )
        assert read_change(api, built["change_low"]["id"])["state"] == ChangeState.MERGED
        release = read_release(api, built["release"]["id"])
        assert release["phase"] == ReleasePhase.CUT
        assert release["readiness_score_attested"] == 94


class TestTrainFreezeCascade:
    """"freeze the releases, defer the in-flight changes, block the approved
    dependents, reconcile the counters, recompute readiness"."""

    def test_freeze_takes_the_train_and_its_open_release_into_frozen(self, api):
        """"every release on the train whose ``phase`` is ``OPEN`` moves to ``phase``
        ``FROZEN``"; ``open_release_count`` "is *not* reduced, because a ``FROZEN``
        release still counts as open".

        Design: Difficulty/transitive_cascade/train_code_freeze_cascades_release_changes_dependents_and_budget
        """
        built = scenario_train_with_approved_dependent_before_freeze(api)

        freeze_train(api, built["train"]["id"])

        train = read_train(api, built["train"]["id"])
        assert train["phase"] == TrainPhase.FROZEN
        assert train["frozen_at"] is not None
        assert train["open_release_count"] == 1
        assert read_release(api, built["release"]["id"])["phase"] == ReleasePhase.FROZEN

    def test_freeze_defers_in_flight_work_and_blocks_the_approved_dependent(self, api):
        """"every change request whose ``state`` is ``DRAFT``, ``RISK_CLASSIFIED`` or
        ``CAB_REVIEW`` moves to ``state`` ``DEFERRED``", and each dependent named by
        an edge pointing at a deferred change "moves from ``state`` ``APPROVED`` to
        ``state`` ``BLOCKED_BY_DEPENDENCY``".

        Design: Difficulty/transitive_cascade/train_code_freeze_cascades_release_changes_dependents_and_budget
        """
        built = scenario_train_with_approved_dependent_before_freeze(api)

        freeze_train(api, built["train"]["id"])

        assert read_change(api, built["prerequisite"]["id"])["state"] == (
            ChangeState.DEFERRED
        )
        assert read_change(api, built["dependent"]["id"])["state"] == (
            ChangeState.BLOCKED_BY_DEPENDENCY
        )

    def test_freeze_gives_back_the_ledger_contribution_of_the_blocked_dependent(
        self, api
    ):
        """"each change that just left ``APPROVED`` gives back its ledger
        contribution: its release's ``committed_change_count`` drops by one and its
        ``risk_score_final`` is subtracted".

        Design: Difficulty/transitive_cascade/train_code_freeze_cascades_release_changes_dependents_and_budget
        """
        built = scenario_train_with_approved_dependent_before_freeze(api)
        assert built["budget_before"] == 38
        assert built["committed_before"] == 1

        freeze_train(api, built["train"]["id"])

        release = read_release(api, built["release"]["id"])
        assert release["committed_change_count"] == 0
        assert release["risk_budget_consumed_points"] == 0

    def test_blocked_dependent_keeps_its_pinned_final_score_and_depth(self, api):
        """The final run "is likewise never recomputed afterwards", and the projected
        figure charges "five points for each change in the set whose ``state`` is
        ``BLOCKED_BY_DEPENDENCY``".

        Design: Difficulty/transitive_cascade/train_code_freeze_cascades_release_changes_dependents_and_budget
        """
        built = scenario_train_with_approved_dependent_before_freeze(api)

        freeze_train(api, built["train"]["id"])

        dependent = read_change(api, built["dependent"]["id"])
        assert dependent["risk_score_final"] == 38
        assert dependent["dependency_depth"] == 1
        assert read_release(api, built["release"]["id"])["readiness_score_projected"] == 95


class TestWithdrawalCompensation:
    """Withdrawal "is the compensating exit"."""

    def test_withdrawal_restores_budget_and_committed_count_exactly(self, api):
        """"the release's ``committed_change_count`` drops by one and the change's
        ``risk_score_final`` is subtracted from ``risk_budget_consumed_points``,
        restoring both quantities to exactly their pre-approval values".

        Design: Difficulty/compensating_invariant/change_withdraw_restores_release_risk_budget_and_committed_count
        """
        built = scenario_two_approved_changes_with_dependency(api)
        assert built["budget_before"] == 71
        assert built["committed_before"] == 2
        assert built["projected_before"] == 100

        withdraw_change(
            api,
            built["prerequisite"]["id"],
            reason="design reverted after review",
        )

        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 0
        assert release["committed_change_count"] == 0

    def test_withdrawing_a_prerequisite_blocks_its_approved_dependent(self, api):
        """"every change whose ``state`` is ``APPROVED`` and which depends on the
        withdrawn change moves to ``state`` ``BLOCKED_BY_DEPENDENCY``, each such
        dependent applying its own counter decrements in turn".

        Design: Difficulty/compensating_invariant/change_withdraw_restores_release_risk_budget_and_committed_count
        """
        built = scenario_two_approved_changes_with_dependency(api)

        withdraw_change(api, built["prerequisite"]["id"])

        assert read_change(api, built["prerequisite"]["id"])["state"] == (
            ChangeState.WITHDRAWN
        )
        assert read_change(api, built["dependent"]["id"])["state"] == (
            ChangeState.BLOCKED_BY_DEPENDENCY
        )
        assert read_release(api, built["release"]["id"])["readiness_score_projected"] == 95

    def test_pinned_final_scores_survive_the_compensation(self, api):
        """The dependent's five dependency points stay pinned: the final run happens
        once on entry into ``APPROVED`` and is never recomputed.

        Design: Difficulty/compensating_invariant/change_withdraw_restores_release_risk_budget_and_committed_count
        """
        built = scenario_two_approved_changes_with_dependency(api)

        withdraw_change(api, built["prerequisite"]["id"])

        assert read_change(api, built["prerequisite"]["id"])["risk_score_final"] == 33
        assert read_change(api, built["dependent"]["id"])["risk_score_final"] == 38


class TestStabilizationCapacity:
    """"two spans that merely touch at a single endpoint do intersect"."""

    def test_cut_is_refused_when_the_spans_touch_at_one_endpoint(self, api):
        """Capacity counts the other releases whose "closed span from ``cut_at`` to
        ``stabilization_end_at`` intersects this release's closed span".

        Design: Difficulty/resource_temporal_overlap/stabilization_capacity_closed_interval_rejects_touching_endpoint
        """
        built = scenario_three_releases_contending_for_one_slot(api)
        assert_instant(
            built["first_cut_response"]["stabilization_end_at"],
            "2026-08-13T00:00:00Z",
            "stabilization_end_at",
        )
        assert built["first_cut_response"]["phase"] == ReleasePhase.CUT

        response = api.cut_release(built["touching_release"]["id"], {}, RELEASE_MANAGER)

        validate_error(
            response, ApiErrorId.ERR_STABILIZATION_CAPACITY_EXCEEDED.value, 409
        )
        assert read_release(api, built["touching_release"]["id"])["phase"] == (
            ReleasePhase.OPEN
        )

    def test_cut_is_admitted_when_the_span_starts_one_second_later(self, api):
        """"``stabilization_end_at`` is the ``cut_at`` instant moved later by the
        train's ``stabilization_hours``", so a one-second gap clears the slot.

        Design: Difficulty/resource_temporal_overlap/stabilization_capacity_closed_interval_rejects_touching_endpoint
        """
        built = scenario_three_releases_contending_for_one_slot(api)

        cut = validate_success(
            api.cut_release(built["clear_release"]["id"], {}, RELEASE_MANAGER)
        )

        assert cut["phase"] == ReleasePhase.CUT
        assert_instant(
            cut["stabilization_end_at"], "2026-08-16T00:00:01Z", "stabilization_end_at"
        )

    def test_only_the_admitted_cuts_lower_the_open_release_count(self, api):
        """A cut drops "the train's ``open_release_count`` ... by one", and the
        refused cut leaves the counter alone.

        Design: Difficulty/resource_temporal_overlap/stabilization_capacity_closed_interval_rejects_touching_endpoint
        """
        built = scenario_three_releases_contending_for_one_slot(api)
        api.cut_release(built["touching_release"]["id"], {}, RELEASE_MANAGER)
        validate_success(api.cut_release(built["clear_release"]["id"], {}, RELEASE_MANAGER))

        assert read_train(api, built["train"]["id"])["open_release_count"] == 1
