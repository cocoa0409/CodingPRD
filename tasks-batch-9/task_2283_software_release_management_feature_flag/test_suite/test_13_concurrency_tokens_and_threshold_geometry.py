"""Expected-version tokens, the version counter itself, and the abort predicate."""

from test_helpers import (
    ApiErrorId,
    CanaryVerdict,
    DeliveryState,
    FlagState,
    PacketState,
    StepState,
    VerificationState,
    assert_canary_numbers,
    assert_deployment_dimensions,
    assert_evidence_index,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    make_evidence_packet_payload,
    make_rollout_step_payload,
)
from test_helpers.fixtures import (
    create_flag,
    current_flag_version,
    current_release_version,
    pause_flag,
    plan_step,
    read_deployment,
    read_flag,
    read_step,
    reset_clock,
    resume_flag,
    run_canary_evaluation,
    scenario_cut_release_and_the_version_read_at_its_creation,
    scenario_staging_canary_with_two_samples_bracketing_the_abort_rate,
    start_soak,
)
from test_helpers.test_users import COMPLIANCE_OFFICER, ENGINEER, SRE

#: The half-open window holding only the 24.9 percent sample.
BELOW_WINDOW_START_AT = "2026-08-10T02:30:00Z"
BELOW_WINDOW_END_AT = "2026-08-10T02:45:00Z"

#: The half-open window holding only the sample sitting exactly on the threshold.
AT_WINDOW_START_AT = "2026-08-10T02:00:00Z"
AT_WINDOW_END_AT = "2026-08-10T02:30:00Z"


class TestFlagTokenGuardsTheLadder:
    """The rung's token is the parent flag's version, not the step's own."""

    def test_the_token_read_before_the_soak_is_refused_and_the_fresh_one_accepted(
        self, api
    ):
        """"Its value must equal the target flag's current ``version``. If any other
        writer has advanced that flag's ``version`` since the client last read the
        flag, the create is rejected with ``ERR_STALE_FLAG_VERSION`` (412) and no step
        is created".

        Design: Corner/cross_cutting_complexity_layers/stale_expected_feature_flag_version_on_rollout_step_create_returns_conflict
        """
        reset_clock(api)
        flag = create_flag(api)
        stale_version = flag["version"]
        first = plan_step(
            api,
            flag["id"],
            target_pct=5,
            soak_minutes=30,
            expected_feature_flag_version=stale_version,
        )
        start_soak(api, first["id"])

        replayed = api.create_rollout_step(
            flag["id"],
            make_rollout_step_payload(stale_version, target_pct=5, soak_minutes=30),
            ENGINEER,
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_FLAG_VERSION.value, 412)
        _, meta = validate_paginated(
            api.list_rollout_steps(ENGINEER, {"feature_flag_id": flag["id"]})
        )
        assert meta["total_count"] == 1

        fresh_version = current_flag_version(api, flag["id"])
        assert fresh_version > stale_version
        second = plan_step(
            api,
            flag["id"],
            target_pct=5,
            soak_minutes=30,
            expected_feature_flag_version=fresh_version,
        )

        assert second["step_index"] == 2
        assert second["state"] == StepState.PLANNED
        assert second["previous_exposure_pct"] is None
        settled = read_flag(api, flag["id"])
        assert settled["state"] == FlagState.ACTIVE_ROLLING_OUT
        assert float(settled["current_exposure_pct"]) == 0.0


class TestReleaseTokenGuardsTheSeal:
    """The second token guards the Release row and carries its own error id."""

    def test_the_version_read_at_creation_no_longer_opens_the_packet(self, api):
        """"Assembling a compliance evidence packet for a release requires
        ``expected_release_version`` in the request body, likewise non-optional, and
        likewise required to equal the target release's current ``version``. A
        mismatch is rejected with ``ERR_STALE_RELEASE_VERSION`` (412)".

        Design: Corner/cross_cutting_complexity_layers/stale_expected_release_version_on_evidence_packet_create_returns_conflict
        """
        built = scenario_cut_release_and_the_version_read_at_its_creation(api)
        release_id = built["release"]["id"]
        stale_version = built["stale_version"]

        refused = api.create_evidence_packet(
            release_id, make_evidence_packet_payload(stale_version), COMPLIANCE_OFFICER
        )
        validate_error(refused, ApiErrorId.ERR_STALE_RELEASE_VERSION.value, 412)
        _, meta = validate_paginated(
            api.list_evidence_packets(release_id, COMPLIANCE_OFFICER)
        )
        assert meta["total_count"] == 0

        fresh_version = current_release_version(api, release_id)
        assert fresh_version > stale_version
        packet = validate_success(
            api.create_evidence_packet(
                release_id,
                make_evidence_packet_payload(fresh_version),
                COMPLIANCE_OFFICER,
            ),
            201,
        )

        assert packet["state"] == PacketState.DRAFT
        assert_evidence_index(
            packet, base_index=75, waiver_credit_points=0, completeness_index=75
        )
        assert packet["waiver_count"] == 0


class TestVersionCounterHasNoGaps:
    """"a counter that increases by one on every mutation of the resource"."""

    def test_the_soak_pause_and_resume_advance_the_flag_one_step_at_a_time(self, api):
        """"Planning also increments the flag's ``version`` by one", then "When the flag
        was still ``DRAFT``, this is also the moment it becomes
        ``ACTIVE_ROLLING_OUT``, with its own ``version`` increment", then a pause
        "sets ``state`` to ``PAUSED`` with a ``version`` increment", and finally
        "Resuming clears ``kill_switch_engaged`` back to false and increments the
        flag's ``version``".

        Design: Corner/cross_cutting_complexity_layers/feature_flag_version_increments_on_every_mutating_write
        """
        reset_clock(api)
        flag = create_flag(api)
        step = plan_step(
            api,
            flag["id"],
            target_pct=5,
            soak_minutes=30,
            expected_feature_flag_version=flag["version"],
        )

        start_soak(api, step["id"])
        after_soak = current_flag_version(api, flag["id"])
        after_second_read = current_flag_version(api, flag["id"])
        paused = pause_flag(api, flag["id"], reason="investigating latency")
        resumed = resume_flag(api, flag["id"])

        # The plan and the DRAFT to ACTIVE_ROLLING_OUT hop are one increment each.
        assert after_soak == flag["version"] + 2
        assert after_second_read == after_soak
        assert paused["version"] == after_soak + 1
        assert resumed["version"] == after_soak + 2
        assert paused["state"] == FlagState.PAUSED
        assert resumed["state"] == FlagState.ACTIVE_ROLLING_OUT
        assert resumed["kill_switch_engaged"] is False
        assert float(resumed["current_exposure_pct"]) == 0.0
        assert read_step(api, step["id"])["state"] == StepState.SOAKING


class TestAbortPredicateIsInclusive:
    """One tenth of a point decides between ``PASS`` and ``FAIL``."""

    def test_the_rate_sitting_exactly_on_the_threshold_aborts_while_24_9_passes(
        self, api
    ):
        """"``abort_triggered`` is true when ``error_rate_pct_rounded`` is at or above
        the deployment's ``abort_error_rate_pct``, or when the evaluation's
        ``latency_p95_ms`` is at or above the deployment's ``abort_latency_p95_ms``.
        The ``verdict`` is ``FAIL`` when ``abort_triggered`` is true and ``PASS``
        otherwise".

        Design: Corner/cross_cutting_complexity_layers/canary_abort_triggers_at_exactly_the_abort_error_rate_threshold
        """
        built = scenario_staging_canary_with_two_samples_bracketing_the_abort_rate(api)
        deployment_id = built["deployment"]["id"]
        assert built["deployment"]["delivery_state"] == DeliveryState.CANARY_SOAK

        below = run_canary_evaluation(
            api, deployment_id, BELOW_WINDOW_START_AT, BELOW_WINDOW_END_AT
        )
        after_below = read_deployment(api, deployment_id)
        at_threshold = run_canary_evaluation(
            api, deployment_id, AT_WINDOW_START_AT, AT_WINDOW_END_AT
        )
        after_at_threshold = read_deployment(api, deployment_id)

        assert_canary_numbers(
            below,
            sample_count=1000,
            error_rate_pct_rounded=24.9,
            latency_p95_ms=300,
            weighted_health_score=58.14,
            verdict=CanaryVerdict.PASS,
            abort_triggered=False,
        )
        assert_deployment_dimensions(
            after_below, DeliveryState.CANARY_SOAK, VerificationState.PASSING
        )
        assert float(after_below["health_score"]) == 58.14
        assert_canary_numbers(
            at_threshold,
            sample_count=8,
            error_rate_pct_rounded=25.0,
            latency_p95_ms=300,
            weighted_health_score=58.0,
            verdict=CanaryVerdict.FAIL,
            abort_triggered=True,
        )
        assert_deployment_dimensions(
            after_at_threshold, DeliveryState.ABORTED, VerificationState.FAILING
        )
        assert float(after_at_threshold["health_score"]) == 58.0
        _, meta = validate_paginated(api.list_canary_evaluations(deployment_id, SRE))
        assert meta["total_count"] == 2
