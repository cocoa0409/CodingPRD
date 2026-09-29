"""The flag rollout ladder, its soak preconditions, and the two abort cascades."""

import pytest

from test_helpers import (
    ApiErrorId,
    CanaryVerdict,
    ChangeState,
    DeliveryState,
    FlagState,
    IncidentDecision,
    IncidentState,
    ReleasePhase,
    StepState,
    VerificationState,
    assert_canary_numbers,
    assert_deployment_dimensions,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    decide_incident,
    read_change,
    read_deployment,
    read_environment,
    read_flag,
    read_incident,
    read_release,
    read_step,
    reset_clock,
    run_canary_evaluation,
    scenario_canary_gated_second_rung_soaking,
    scenario_flag_guarding_merged_change,
    scenario_released_release_with_rolling_flag_and_open_incident,
    ship_the_release_through_production,
    soaking_flag,
    start_soak,
)
from test_helpers.test_users import ENGINEER, SRE


class TestPauseResumeCycle:
    """Pausing "stops further advancement rather than retracting the traffic already
    exposed"."""

    def test_flag_returns_to_active_rolling_out_after_each_resume(self, api):
        """"Resuming closes the rollout cycle back to ``ACTIVE_ROLLING_OUT``",
        requiring the flag to be ``PAUSED`` and the caller to be its owner.

        Design: Difficulty/non_linear_state_machine/feature_flag_pause_resume_cycle_returns_to_active_rolling_out_twice
        """
        reset_clock(api)
        built = soaking_flag(api)
        flag_id = built["flag"]["id"]

        first_pause = validate_success(
            api.pause_flag(flag_id, {"reason": "latency regression suspected"}, ENGINEER)
        )
        first_resume = validate_success(api.resume_flag(flag_id, {}, ENGINEER))
        second_pause = validate_success(api.pause_flag(flag_id, {}, SRE))
        second_resume = validate_success(api.resume_flag(flag_id, {}, ENGINEER))

        assert first_pause["state"] == FlagState.PAUSED
        assert first_resume["state"] == FlagState.ACTIVE_ROLLING_OUT
        assert second_pause["state"] == FlagState.PAUSED
        assert second_resume["state"] == FlagState.ACTIVE_ROLLING_OUT

    def test_manual_pause_leaves_the_kill_switch_and_the_exposure_alone(self, api):
        """"it leaves ``kill_switch_engaged`` unchanged, because that flag is reserved
        to mark pauses the *system* forced; and it leaves ``current_exposure_pct``
        untouched".

        Design: Difficulty/non_linear_state_machine/feature_flag_pause_resume_cycle_returns_to_active_rolling_out_twice
        """
        reset_clock(api)
        built = soaking_flag(api)
        flag_id = built["flag"]["id"]

        validate_success(api.pause_flag(flag_id, {}, ENGINEER))
        validate_success(api.resume_flag(flag_id, {}, ENGINEER))
        validate_success(api.pause_flag(flag_id, {}, SRE))
        validate_success(api.resume_flag(flag_id, {}, ENGINEER))

        flag = read_flag(api, flag_id)
        assert flag["kill_switch_engaged"] is False
        assert flag["current_exposure_pct"] == pytest.approx(0, abs=0.01)
        assert flag["applied_step_count"] == 0

    def test_the_soaking_rung_survives_the_whole_cycle(self, api):
        """Pausing is "available to both an ``Engineer`` and an ``SRE``" and touches
        the rollout dimension only, so the rung stays ``SOAKING``.

        Design: Difficulty/non_linear_state_machine/feature_flag_pause_resume_cycle_returns_to_active_rolling_out_twice
        """
        reset_clock(api)
        built = soaking_flag(api)

        validate_success(api.pause_flag(built["flag"]["id"], {}, ENGINEER))
        validate_success(api.resume_flag(built["flag"]["id"], {}, ENGINEER))
        validate_success(api.pause_flag(built["flag"]["id"], {}, SRE))
        validate_success(api.resume_flag(built["flag"]["id"], {}, ENGINEER))

        assert read_step(api, built["step"]["id"])["state"] == StepState.SOAKING


class TestSoakRequiresDeployedGuards:
    """"every change linked to the flag through a change-to-flag link must be in
    ``state`` ``DEPLOYED``"."""

    def test_soak_is_refused_while_the_guarded_change_is_only_merged(self, api):
        """The linked-change precondition is reported as ``ERR_CHANGE_STATE_INVALID``,
        and the refused request leaves the rung and the flag untouched.

        Design: Difficulty/cross_entity_state_dependency/rollout_step_soak_requires_every_linked_change_deployed
        """
        built = scenario_flag_guarding_merged_change(api)

        response = api.start_soak(built["step"]["id"], {}, ENGINEER)

        validate_error(response, ApiErrorId.ERR_CHANGE_STATE_INVALID.value, 409)
        assert read_step(api, built["step"]["id"])["state"] == StepState.PLANNED
        assert read_flag(api, built["flag"]["id"])["state"] == FlagState.DRAFT

    def test_soak_starts_once_the_release_ships_and_the_change_is_deployed(self, api):
        """Shipping promotes work: "every change on the release whose ``state`` is
        ``MERGED`` moves to ``state`` ``DEPLOYED``", which opens the soak.

        Design: Difficulty/cross_entity_state_dependency/rollout_step_soak_requires_every_linked_change_deployed
        """
        built = scenario_flag_guarding_merged_change(api)
        ship_the_release_through_production(
            api, built["release"]["id"], built["environment"]["id"]
        )
        release = read_release(api, built["release"]["id"])
        assert release["phase"] == ReleasePhase.RELEASED
        assert release["readiness_score_attested"] == 100
        assert read_change(api, built["change"]["id"])["state"] == ChangeState.DEPLOYED

        soaking = start_soak(api, built["step"]["id"])

        assert soaking["state"] == StepState.SOAKING
        assert soaking["previous_exposure_pct"] == pytest.approx(0, abs=0.01)
        assert read_flag(api, built["flag"]["id"])["state"] == (
            FlagState.ACTIVE_ROLLING_OUT
        )


class TestCanaryAbortRestoresExposure:
    """"Only a step abort restores exposure."""

    def test_failing_evaluation_reports_the_abort_verdict(self, api):
        """"``abort_triggered`` is true when ``error_rate_pct_rounded`` is at or above
        the deployment's ``abort_error_rate_pct``", and the verdict is then ``FAIL``.

        Design: Difficulty/compensating_invariant/rollout_step_abort_restores_flag_exposure_and_leaves_applied_count
        """
        built = scenario_canary_gated_second_rung_soaking(api)

        evaluation = run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:30:00Z",
            "2026-08-10T02:45:00Z",
        )

        assert_canary_numbers(
            evaluation,
            sample_count=10,
            error_rate_pct_rounded=40.0,
            latency_p95_ms=300,
            weighted_health_score=36.4,
            verdict=CanaryVerdict.FAIL,
            abort_triggered=True,
        )

    def test_abort_restores_the_previous_exposure_and_keeps_the_applied_count(self, api):
        """"every rollout step whose ``deployment_id`` is this deployment and whose
        ``state`` is ``SOAKING`` becomes ``ABORTED``, and its flag's
        ``current_exposure_pct`` is restored to that step's
        ``previous_exposure_pct`` while the flag's ``applied_step_count`` stays
        unchanged".

        Design: Difficulty/compensating_invariant/rollout_step_abort_restores_flag_exposure_and_leaves_applied_count
        """
        built = scenario_canary_gated_second_rung_soaking(api)
        assert built["exposure_before_abort"] == pytest.approx(5, abs=0.01)
        assert built["step_two_previous_exposure_pct"] == pytest.approx(5, abs=0.01)

        run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:30:00Z",
            "2026-08-10T02:45:00Z",
        )

        flag = read_flag(api, built["flag"]["id"])
        assert flag["current_exposure_pct"] == pytest.approx(5, abs=0.01)
        assert flag["applied_step_count"] == 1
        assert read_step(api, built["step_two"]["id"])["state"] == StepState.ABORTED
        assert read_step(api, built["step_one"]["id"])["state"] == StepState.APPLIED

    def test_abort_forces_the_flag_paused_with_the_kill_switch_engaged(self, api):
        """"each such flag whose ``state`` is ``ACTIVE_ROLLING_OUT`` moves to
        ``PAUSED`` with ``kill_switch_engaged`` set to true".

        Design: Difficulty/compensating_invariant/rollout_step_abort_restores_flag_exposure_and_leaves_applied_count
        """
        built = scenario_canary_gated_second_rung_soaking(api)

        run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:30:00Z",
            "2026-08-10T02:45:00Z",
        )

        flag = read_flag(api, built["flag"]["id"])
        assert flag["state"] == FlagState.PAUSED
        assert flag["kill_switch_engaged"] is True

    def test_abort_frees_the_environment_and_leaves_the_release_stabilizing(self, api):
        """"the deployment's ``delivery_state`` becomes ``ABORTED`` and its
        ``verification_state`` becomes ``FAILING`` ... and the environment's
        ``active_deployment_count`` drops by one".

        Design: Difficulty/compensating_invariant/rollout_step_abort_restores_flag_exposure_and_leaves_applied_count
        """
        built = scenario_canary_gated_second_rung_soaking(api)

        run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:30:00Z",
            "2026-08-10T02:45:00Z",
        )

        deployment = read_deployment(api, built["deployment"]["id"])
        assert_deployment_dimensions(
            deployment, DeliveryState.ABORTED, VerificationState.FAILING
        )
        assert deployment["health_score"] == pytest.approx(36.4, abs=0.01)
        assert read_environment(api, built["environment"]["id"])[
            "active_deployment_count"
        ] == 0
        assert read_release(api, built["release"]["id"])["phase"] == (
            ReleasePhase.STABILIZING
        )


class TestIncidentRollbackCascade:
    """"A ``ROLLBACK`` decision fires the deepest cascade in the system"."""

    def test_incident_links_the_recent_release_and_its_completed_deployment(self, api):
        """Candidates are ranked "by ``cut_at`` descending -- most recently cut first",
        and the deployment "is then chosen from that selected release only".

        Design: Difficulty/transitive_cascade/incident_rollback_cascades_deployment_release_flag_steps_and_changes
        """
        built = scenario_released_release_with_rolling_flag_and_open_incident(api)

        incident = read_incident(api, built["incident"]["id"])

        assert incident["linked_release_id"] == built["release"]["id"]
        assert incident["linked_deployment_id"] == built["deployment"]["id"]
        assert incident["state"] == IncidentState.OPEN

    def test_rollback_decision_rolls_the_deployment_and_the_release_back(self, api):
        """"Hop one takes the linked deployment from ``delivery_state`` ``COMPLETED``
        to ``ROLLED_BACK``"; hop two takes the release "to the terminal ``phase``
        ``ROLLED_BACK``".

        Design: Difficulty/transitive_cascade/incident_rollback_cascades_deployment_release_flag_steps_and_changes
        """
        built = scenario_released_release_with_rolling_flag_and_open_incident(api)

        decided = decide_incident(
            api, built["incident"]["id"], IncidentDecision.ROLLBACK
        )

        assert decided["state"] == IncidentState.DECIDED
        assert decided["decision"] == IncidentDecision.ROLLBACK
        assert read_deployment(api, built["deployment"]["id"])["delivery_state"] == (
            DeliveryState.ROLLED_BACK
        )
        release = read_release(api, built["release"]["id"])
        assert release["phase"] == ReleasePhase.ROLLED_BACK
        assert release["rolled_back_at"] is not None

    def test_rollback_pauses_the_guard_flag_and_cleans_its_ladder(self, api):
        """"every step whose ``state`` is ``PLANNED`` becomes ``VOIDED``, and every
        step whose ``state`` is ``SOAKING`` becomes ``ABORTED`` with the flag's
        ``current_exposure_pct`` restored to that step's ``previous_exposure_pct``".

        Design: Difficulty/transitive_cascade/incident_rollback_cascades_deployment_release_flag_steps_and_changes
        """
        built = scenario_released_release_with_rolling_flag_and_open_incident(api)

        decide_incident(api, built["incident"]["id"], IncidentDecision.ROLLBACK)

        flag = read_flag(api, built["flag"]["id"])
        assert flag["state"] == FlagState.PAUSED
        assert flag["kill_switch_engaged"] is True
        assert flag["current_exposure_pct"] == pytest.approx(5, abs=0.01)
        assert flag["applied_step_count"] == 1
        assert read_step(api, built["step_one"]["id"])["state"] == StepState.APPLIED
        assert read_step(api, built["step_two"]["id"])["state"] == StepState.ABORTED
        assert read_step(api, built["step_three"]["id"])["state"] == StepState.VOIDED

    def test_rollback_unverifies_the_deployed_change_without_demoting_it(self, api):
        """"the changes stay ``DEPLOYED``, but their ``deployment_verified`` reverts to
        false and ``verified_change_count`` falls back to 0".

        Design: Difficulty/transitive_cascade/incident_rollback_cascades_deployment_release_flag_steps_and_changes
        """
        built = scenario_released_release_with_rolling_flag_and_open_incident(api)

        decide_incident(api, built["incident"]["id"], IncidentDecision.ROLLBACK)

        change = read_change(api, built["change"]["id"])
        assert change["state"] == ChangeState.DEPLOYED
        assert change["deployment_verified"] is False
        assert read_release(api, built["release"]["id"])["verified_change_count"] == 0
