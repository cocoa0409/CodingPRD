"""Canary analysis arithmetic, verification waivers, and deployment window rules."""

import pytest

from test_helpers import (
    ApiErrorId,
    CanaryVerdict,
    DeliveryState,
    ReleasePhase,
    VerificationState,
    assert_canary_numbers,
    assert_deployment_dimensions,
    expected_weighted_error_rate,
    expected_weighted_health_score,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import make_deployment_payload
from test_helpers.fixtures import (
    complete_deployment,
    read_deployment,
    read_environment,
    read_release,
    reserve_deployment,
    run_canary_evaluation,
    scenario_canary_deployment_with_mixed_cohort_samples,
    scenario_cut_release_with_reserved_window,
    scenario_open_release_and_environment,
    scenario_staging_canary_with_sample_outside_window,
    scenario_two_reserved_windows_one_running,
    set_clock,
)
from test_helpers.test_users import RELEASE_MANAGER, SRE


class TestCanaryErrorRateArithmetic:
    """"this rounding happens per row, before any weighting"."""

    def test_per_row_rounding_first_yields_a_different_weighted_mean(self, api):
        """"Summing raw error counts over raw request counts and rounding once at the
        end is a different algorithm and yields a different number; it is not what
        this specification requires."

        Design: Difficulty/combinatorial_formula/canary_error_rate_per_signal_rounding_then_request_weighted_mean
        """
        built = scenario_canary_deployment_with_mixed_cohort_samples(api)

        evaluation = run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:30:00Z",
        )

        assert evaluation["error_rate_pct_rounded"] == pytest.approx(22.23, abs=0.01)
        assert evaluation["error_rate_pct_rounded"] != pytest.approx(22.22, abs=0.001)
        assert evaluation["error_rate_pct_rounded"] == pytest.approx(
            expected_weighted_error_rate(
                [
                    {"request_count": 6, "error_count": 1},
                    {"request_count": 3, "error_count": 1},
                ]
            ),
            abs=0.01,
        )

    def test_baseline_rows_and_the_window_end_instant_are_excluded(self, api):
        """"``BASELINE`` samples are excluded from every term, ``sample_count``
        included", and the window is "at or after the window start and strictly
        before the window end".

        Design: Difficulty/combinatorial_formula/canary_error_rate_per_signal_rounding_then_request_weighted_mean
        """
        built = scenario_canary_deployment_with_mixed_cohort_samples(api)

        evaluation = run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:30:00Z",
        )

        assert evaluation["sample_count"] == 9
        assert evaluation["latency_p95_ms"] == 420

    def test_weighted_health_score_passes_below_the_abort_criteria(self, api):
        """"The ``weighted_health_score`` is six tenths of the error component plus
        four tenths of the latency component, rounded half up to two decimal
        places."

        Design: Difficulty/combinatorial_formula/canary_error_rate_per_signal_rounding_then_request_weighted_mean
        """
        built = scenario_canary_deployment_with_mixed_cohort_samples(api)

        evaluation = run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:30:00Z",
        )

        assert_canary_numbers(
            evaluation,
            sample_count=9,
            error_rate_pct_rounded=22.23,
            latency_p95_ms=420,
            weighted_health_score=59.59,
            verdict=CanaryVerdict.PASS,
            abort_triggered=False,
        )
        assert evaluation["weighted_health_score"] == pytest.approx(
            expected_weighted_health_score(22.23, 420, 25.0, 800), abs=0.01
        )

    def test_deployment_mirrors_the_verdict_and_the_score(self, api):
        """"The deployment's ``verification_state`` is then written from the verdict"
        and "its ``health_score`` is set to the evaluation's
        ``weighted_health_score``".

        Design: Difficulty/combinatorial_formula/canary_error_rate_per_signal_rounding_then_request_weighted_mean
        """
        built = scenario_canary_deployment_with_mixed_cohort_samples(api)

        run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:30:00Z",
        )

        deployment = read_deployment(api, built["deployment"]["id"])
        assert_deployment_dimensions(
            deployment, DeliveryState.CANARY_SOAK, VerificationState.PASSING
        )
        assert deployment["health_score"] == pytest.approx(59.59, abs=0.01)


class TestInconclusiveCanaryAnalysis:
    """"If ``sample_count`` is below the deployment's ``min_sample_count``, the
    analysis stops there"."""

    def test_no_canary_row_inside_the_window_is_inconclusive_with_zeroed_numbers(
        self, api
    ):
        """""``verdict`` is ``INCONCLUSIVE``, ``abort_triggered`` is false, and
        ``error_rate_pct_rounded``, ``latency_p95_ms`` and ``weighted_health_score``
        are all recorded as 0".

        Design: Difficulty/boundary_precision_check/canary_evaluation_zero_canary_samples_in_window_is_inconclusive
        """
        built = scenario_staging_canary_with_sample_outside_window(api)

        evaluation = run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:30:00Z",
        )

        assert_canary_numbers(
            evaluation,
            sample_count=0,
            error_rate_pct_rounded=0,
            latency_p95_ms=0,
            weighted_health_score=0,
            verdict=CanaryVerdict.INCONCLUSIVE,
            abort_triggered=False,
        )

    def test_verification_state_follows_the_inconclusive_verdict(self, api):
        """The verdict writes ``INCONCLUSIVE`` onto the deployment, whose
        ``health_score`` "always mirrors the latest-created evaluation".

        Design: Difficulty/boundary_precision_check/canary_evaluation_zero_canary_samples_in_window_is_inconclusive
        """
        built = scenario_staging_canary_with_sample_outside_window(api)

        run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:30:00Z",
        )

        deployment = read_deployment(api, built["deployment"]["id"])
        assert deployment["verification_state"] == VerificationState.INCONCLUSIVE
        assert deployment["health_score"] == pytest.approx(0, abs=0.01)

    def test_waive_verification_is_honoured_outside_production(self, api):
        """"setting it true is honoured **only** when the deployment's
        ``verification_state`` is currently ``INCONCLUSIVE`` **and** the target
        environment's ``tier`` is not ``PROD``".

        Design: Difficulty/boundary_precision_check/canary_evaluation_zero_canary_samples_in_window_is_inconclusive
        """
        built = scenario_staging_canary_with_sample_outside_window(api)
        run_canary_evaluation(
            api,
            built["deployment"]["id"],
            "2026-08-10T02:00:00Z",
            "2026-08-10T02:30:00Z",
        )

        completed = complete_deployment(
            api, built["deployment"]["id"], waive_verification=True
        )

        assert_deployment_dimensions(
            completed, DeliveryState.COMPLETED, VerificationState.WAIVED
        )
        assert read_environment(api, built["environment"]["id"])[
            "active_deployment_count"
        ] == 0


class TestStartPreconditionPriority:
    """A rank-8 state conflict on the path target outranks the rank-31 window rule."""

    def test_restarting_a_running_deployment_reports_the_state_conflict(self, api):
        """"Starting a deployment is an ``SRE`` act on a ``SCHEDULED`` deployment",
        and the ladder stops at the first failing check.

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_deploy_window_on_duplicate_deployment_start
        """
        built = scenario_two_reserved_windows_one_running(api)

        response = api.start_deployment(built["running_deployment"]["id"], {}, SRE)

        validate_error(response, ApiErrorId.ERR_DEPLOYMENT_STATE_INVALID.value, 409)

    def test_starting_a_scheduled_deployment_past_its_window_reports_the_window_rule(
        self, api
    ):
        """"the logical clock must lie at or after ``window_start_at`` and strictly
        before ``window_end_at`` (``ERR_DEPLOY_WINDOW_VIOLATION``)".

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_deploy_window_on_duplicate_deployment_start
        """
        built = scenario_two_reserved_windows_one_running(api)

        response = api.start_deployment(built["scheduled_deployment"]["id"], {}, SRE)

        validate_error(response, ApiErrorId.ERR_DEPLOY_WINDOW_VIOLATION.value, 409)

    def test_neither_refusal_moves_a_delivery_state_or_the_occupancy_counter(self, api):
        """The ladder applies "**no side effect whatsoever** -- no counter moves, no
        state changes, no timestamp is stamped".

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_deploy_window_on_duplicate_deployment_start
        """
        built = scenario_two_reserved_windows_one_running(api)

        api.start_deployment(built["running_deployment"]["id"], {}, SRE)
        api.start_deployment(built["scheduled_deployment"]["id"], {}, SRE)

        assert read_deployment(api, built["running_deployment"]["id"])[
            "delivery_state"
        ] == DeliveryState.IN_PROGRESS
        assert read_deployment(api, built["scheduled_deployment"]["id"])[
            "delivery_state"
        ] == DeliveryState.SCHEDULED
        assert read_environment(api, built["environment"]["id"])[
            "active_deployment_count"
        ] == 1


class TestCooldownOccupancy:
    """Occupied spans are "each of those spans extended at the end by the
    environment's ``cooldown_minutes``"."""

    def test_window_inside_the_cooldown_buffer_is_refused(self, api):
        """"any intersection is refused with ``ERR_DEPLOYMENT_WINDOW_CONFLICT``".

        Design: Difficulty/resource_temporal_overlap/deployment_window_cooldown_buffer_rejects_overlap_but_admits_adjacency
        """
        built = scenario_cut_release_with_reserved_window(api)

        response = api.create_deployment(
            built["release"]["id"],
            make_deployment_payload(
                built["environment"]["id"],
                window_start_at="2026-08-10T04:15:00Z",
                window_end_at="2026-08-10T05:15:00Z",
            ),
            SRE,
        )

        validate_error(response, ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT.value, 409)

    def test_window_starting_exactly_where_the_cooldown_ends_is_admitted(self, api):
        """The requested span is half-open, so a window opening at the cooldown's end
        does not intersect the occupied span.

        Design: Difficulty/resource_temporal_overlap/deployment_window_cooldown_buffer_rejects_overlap_but_admits_adjacency
        """
        built = scenario_cut_release_with_reserved_window(api)

        reserved = reserve_deployment(
            api,
            built["release"]["id"],
            built["environment"]["id"],
            window_start_at="2026-08-10T04:30:00Z",
            window_end_at="2026-08-10T05:30:00Z",
        )

        assert_deployment_dimensions(
            reserved, DeliveryState.SCHEDULED, VerificationState.PENDING
        )

    def test_both_admitted_reservations_leave_the_environment_unoccupied(self, api):
        """A new environment starts with ``active_deployment_count`` 0 -- "the number
        of its deployments whose ``delivery_state`` is ``IN_PROGRESS`` or
        ``CANARY_SOAK``".

        Design: Difficulty/resource_temporal_overlap/deployment_window_cooldown_buffer_rejects_overlap_but_admits_adjacency
        """
        built = scenario_cut_release_with_reserved_window(api)
        reserve_deployment(
            api,
            built["release"]["id"],
            built["environment"]["id"],
            window_start_at="2026-08-10T04:30:00Z",
            window_end_at="2026-08-10T05:30:00Z",
        )

        _, meta = validate_paginated(
            api.list_deployments(SRE, {"environment_id": built["environment"]["id"]})
        )
        assert meta["total_count"] == 2
        assert read_environment(api, built["environment"]["id"])[
            "active_deployment_count"
        ] == 0


class TestReservationRequiresACutRelease:
    """"the release must be in ``phase`` ``CUT``, ``STABILIZING`` or ``RELEASED``"."""

    def test_reservation_against_an_open_release_is_refused(self, api):
        """"the reservation is refused with ``ERR_RELEASE_PHASE_INVALID``".

        Design: Difficulty/cross_entity_state_dependency/deployment_creation_requires_release_phase_cut_or_later
        """
        built = scenario_open_release_and_environment(api)

        response = api.create_deployment(
            built["release"]["id"],
            make_deployment_payload(
                built["environment"]["id"],
                window_start_at="2026-08-10T02:00:00Z",
                window_end_at="2026-08-10T04:00:00Z",
            ),
            SRE,
        )

        validate_error(response, ApiErrorId.ERR_RELEASE_PHASE_INVALID.value, 409)
        _, meta = validate_paginated(
            api.list_deployments(SRE, {"release_id": built["release"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_reservation_succeeds_once_the_release_has_been_cut(self, api):
        """A reserved deployment "begins with ``delivery_state`` ``SCHEDULED``,
        ``verification_state`` ``PENDING``".

        Design: Difficulty/cross_entity_state_dependency/deployment_creation_requires_release_phase_cut_or_later
        """
        built = scenario_open_release_and_environment(api)
        set_clock(api, "2026-08-08T00:00:00Z")
        cut = validate_success(api.cut_release(built["release"]["id"], {}, RELEASE_MANAGER))
        assert cut["phase"] == ReleasePhase.CUT

        reserved = reserve_deployment(
            api,
            built["release"]["id"],
            built["environment"]["id"],
            window_start_at="2026-08-10T02:00:00Z",
            window_end_at="2026-08-10T04:00:00Z",
        )

        assert_deployment_dimensions(
            reserved, DeliveryState.SCHEDULED, VerificationState.PENDING
        )
        assert read_release(api, built["release"]["id"])["evidence_packet_required"] is (
            False
        )
