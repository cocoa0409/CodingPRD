"""Measurement runs, their admissibility ladder, and the evidence cascade that
withdrawing one sets off.

Four families live here: the five-hop invalidation cascade with its
`evidence_gap` fan-out, the temporal-versus-shape rejection order on recording a
run, the probe cooldown buffer against probe capacity, and the compensating
invariant that returns `evidence_sample_total` to its prior value without
collateral damage.
"""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers.assertions import (
    assert_evidence_sample_total,
    assert_evidence_sample_total_matches_runs,
    assert_label_dimensions,
    assert_pinned_typical_figures,
    assert_posture,
)
from test_helpers.constants import (
    PEAK_HOUR_MEDIAN_POOLED_COUNT,
    PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
    PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
    REFERENCE_NOW,
)
from test_helpers.factories import (
    build_disclosure_payload,
    build_invalidate_run_payload,
    build_test_run_payload,
)
from test_helpers.fixtures import (
    build_reference_environment,
    create_measurement_probe,
    create_published_methodology,
    create_reference_plan,
    create_service_plan,
    file_complaint,
    read_attestation,
    read_label,
    read_service_plan,
    read_test_run,
    record_test_run,
    set_clock,
    triage_complaint,
)
from test_helpers.test_users import NETWORK_ENGINEER_HEADERS, RETAIL_AGENT_HEADERS
from test_helpers.types import (
    AttestationStatus,
    ComplaintState,
    DisclosureChannel,
    LabelPosture,
    PublicationState,
    SubstantiationStatus,
    TestRunStatus,
)

# ---------------------------------------------------------------------------
# Pre-computed figures of the reference world (advertised 300/140 Mbps, six
# samples of which four fall in the 19:00-23:00 UTC peak band, methodology
# `min_samples_required` 4).
# ---------------------------------------------------------------------------

REFERENCE_RUN_SAMPLE_COUNT = 6
EVIDENCE_TOTAL_AFTER_FULL_INVALIDATION = 0
PINNED_MIN_SAMPLES_REQUIRED = 4
REFERENCE_NET_MONTHLY_INTRO_CENTS = 3766
REVOKED_REASON_EVIDENCE_BELOW_MINIMUM = "EVIDENCE_BELOW_MINIMUM"

CASCADE_INVALIDATION_REASON = "Probe firmware defect invalidates the August window"

# The reference measurement window is closed on [2026-08-03, 2026-08-09T23:00],
# so with the 60-minute trailing cooldown its buffered end is 2026-08-10T00:00.
BUFFERED_COOLDOWN_END = "2026-08-10T00:00:00Z"
ONE_MINUTE_PAST_BUFFERED_END = "2026-08-10T00:01:00Z"
BOUNDARY_WINDOW_END = "2026-08-11T00:00:00Z"

# The one-day window that clears every admissibility check on the reference
# probe, and the two-sample supplementary window used by the compensation.
ADMISSIBLE_WINDOW_START = "2026-08-11T00:01:00Z"
ADMISSIBLE_WINDOW_END = "2026-08-12T00:00:00Z"
SUPPLEMENTARY_WINDOW_START = "2026-08-11T00:00:00Z"
SUPPLEMENTARY_WINDOW_END = "2026-08-12T00:00:00Z"

FUTURE_LONG_WINDOW_START = "2026-09-05T00:00:00Z"
FUTURE_LONG_WINDOW_END = "2026-09-20T00:00:00Z"
FUTURE_SHORT_WINDOW_END = "2026-09-06T00:00:00Z"
PAST_LONG_WINDOW_END = "2026-08-26T00:00:00Z"


def _to_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_instant(actual: Optional[str], expected_iso: str, field: str) -> None:
    assert actual is not None, f"{field} should have been set from the logical clock"
    assert _to_instant(actual) == _to_instant(expected_iso), (
        f"{field}: expected the logical clock {expected_iso}, got {actual}"
    )


def _sample(observed_at: str, download: float = 250, upload: float = 120,
            latency: int = 20) -> Dict[str, Any]:
    return {
        "observed_at": observed_at,
        "download_mbps": download,
        "upload_mbps": upload,
        "latency_ms": latency,
    }


def _measurement_world() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Clock at the reference instant, the reference plan with its five fee
    lines, a published methodology, a probe, and one recorded six-sample run."""
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    run = record_test_run(probe["id"], plan["id"], methodology["id"])
    return plan, methodology, probe, run


def _record_run(
    probe_id: str,
    plan_id: str,
    methodology_doc_id: str,
    window_start: str,
    window_end: str,
    samples: list,
):
    """The trigger call itself, so the raw response can be validated."""
    payload = build_test_run_payload(
        probe_id,
        plan_id,
        methodology_doc_id,
        window_start=window_start,
        window_end=window_end,
        samples=samples,
    )
    return api_client.create_test_run(payload, NETWORK_ENGINEER_HEADERS)


# ===========================================================================
# The five-hop invalidation cascade
# ===========================================================================


def _cascade_world() -> Tuple[Any, str]:
    """The reference world plus one `TRIAGED` complaint disputing the published
    label, used only to observe the fan-out consequence."""
    env = build_reference_environment()
    complaint = file_complaint(env.account_id, env.label_id)
    triage_complaint(complaint["id"])
    return env, complaint["id"]


class TestInvalidationCascade:
    """Withdrawing one run walks run -> plan total -> attestation -> label ->
    posture, then fans out to the open complaints."""

    def test_invalidating_the_run_propagates_the_five_hop_evidence_cascade(self):
        """Each hop is caused by the one before it, and the pinned label figures survive.

        PRD: "Withdrawing a single measurement run can knock a plan's evidence pool
        below the minimum its methodology demands, which revokes the attestation,
        leaves the published label standing but unsubstantiated, freezes the plan's
        disclosure posture, and flags every complaint that is still disputing that
        label."

        Design: Difficulty/transitive_cascade/invalidate_run_five_hop_substantiation_cascade
        """
        env, _ = _cascade_world()
        assert_evidence_sample_total(env.reload_plan(), REFERENCE_RUN_SAMPLE_COUNT)

        response = api_client.invalidate_test_run(
            env.run_id,
            build_invalidate_run_payload(reason=CASCADE_INVALIDATION_REASON),
            NETWORK_ENGINEER_HEADERS,
        )
        run = validate_success(response)

        # Hop 1: the run leaves the evidence pool.
        assert run["status"] == TestRunStatus.INVALIDATED.value, (
            f"hop 1: status should be INVALIDATED, got {run['status']}"
        )
        _assert_same_instant(run["invalidated_at"], REFERENCE_NOW, "invalidated_at")
        assert run["invalidation_reason"] == CASCADE_INVALIDATION_REASON, (
            "hop 1: invalidation_reason must record the supplied reason"
        )

        # Hop 2, caused by hop 1: the plan total is recomputed from the
        # remaining INCLUDED runs, and the invalidated run held all six samples.
        plan = env.reload_plan()
        assert_evidence_sample_total(plan, EVIDENCE_TOTAL_AFTER_FULL_INVALIDATION)

        # Hop 3, caused by hop 2: the pinned minimum 4 now exceeds the total 0.
        attestation = env.reload_attestation()
        assert attestation["status"] == AttestationStatus.REVOKED.value, (
            f"hop 3: status should be REVOKED, got {attestation['status']}"
        )
        assert attestation["revoked_reason"] == REVOKED_REASON_EVIDENCE_BELOW_MINIMUM, (
            "hop 3: revoked_reason should be EVIDENCE_BELOW_MINIMUM"
        )
        assert (
            attestation["methodology_snapshot"]["min_samples_required"]
            == PINNED_MIN_SAMPLES_REQUIRED
        ), "the pinned minimum is what the recomputed total is compared against"

        # Hop 4, caused by hop 3: the label loses substantiation but stays published.
        label = env.reload_label()
        assert_label_dimensions(
            label,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.UNSUBSTANTIATED.value,
        )

        # Hop 5, caused by hop 4.
        assert_posture(plan, LabelPosture.FROZEN.value)

        # Hop 4 leaves the pinned disclosure figures intact.
        assert_pinned_typical_figures(
            label,
            PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
            PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
            PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
        )
        assert label["net_monthly_intro_cents"] == REFERENCE_NET_MONTHLY_INTRO_CENTS, (
            "the published label keeps the net introductory figure it disclosed"
        )

    def test_invalidation_fans_out_the_evidence_gap_without_moving_the_complaint_state(
        self,
    ):
        """The fan-out flags the open complaint; it does not advance its state.

        PRD: "One further consequence follows from hop 4 without being part of the
        declared five-hop chain: every complaint whose `disputed_label_version_id`
        names that label and whose `state` is not `UPHELD`, `DISMISSED` or
        `WITHDRAWN` has `evidence_gap` set to true, recording that the disputed
        label lost its substantiation while the investigation was still open."

        Design: Difficulty/transitive_cascade/invalidate_run_five_hop_substantiation_cascade
        """
        env, complaint_id = _cascade_world()
        before = validate_success(
            api_client.get_complaint(complaint_id, NETWORK_ENGINEER_HEADERS)
        )
        assert before["evidence_gap"] is False, (
            "the complaint starts without an evidence gap"
        )

        validate_success(
            api_client.invalidate_test_run(
                env.run_id,
                build_invalidate_run_payload(reason=CASCADE_INVALIDATION_REASON),
                NETWORK_ENGINEER_HEADERS,
            )
        )

        after = validate_success(
            api_client.get_complaint(complaint_id, NETWORK_ENGINEER_HEADERS)
        )
        assert after["evidence_gap"] is True, (
            "the complaint disputing the now-unsubstantiated label must be flagged"
        )
        assert after["state"] == ComplaintState.TRIAGED.value, (
            f"the fan-out must not advance the complaint, got {after['state']}"
        )

    def test_frozen_posture_blocks_every_disclosure_channel_after_the_cascade(self):
        """Hop 5 is observable downstream: both channels are refused.

        PRD: "`FROZEN` blocks every disclosure on either channel and every notice
        of either type, answering `ERR_PLAN_POSTURE_FROZEN` (409)."

        Design: Difficulty/transitive_cascade/invalidate_run_five_hop_substantiation_cascade
        """
        env, _ = _cascade_world()
        validate_success(
            api_client.invalidate_test_run(
                env.run_id,
                build_invalidate_run_payload(reason=CASCADE_INVALIDATION_REASON),
                NETWORK_ENGINEER_HEADERS,
            )
        )
        assert_posture(env.reload_plan(), LabelPosture.FROZEN.value)

        for channel in (
            DisclosureChannel.POINT_OF_SALE.value,
            DisclosureChannel.ACCOUNT_PORTAL.value,
        ):
            response = api_client.record_label_disclosure(
                env.account_id,
                build_disclosure_payload(channel=channel),
                RETAIL_AGENT_HEADERS,
            )
            validate_error(response, ApiErrorId.ERR_PLAN_POSTURE_FROZEN.value)

    def test_second_invalidation_is_rejected_and_leaves_the_recomputed_total_at_zero(
        self,
    ):
        """The transition is not idempotent, and the refused retry moves nothing.

        PRD: "A `NetworkEngineer` invalidates a run by supplying a `reason`; the run
        must still be `INCLUDED`, or the request answers
        `ERR_TEST_RUN_ALREADY_INVALIDATED`."

        Design: Difficulty/transitive_cascade/invalidate_run_five_hop_substantiation_cascade
        """
        env, _ = _cascade_world()
        validate_success(
            api_client.invalidate_test_run(
                env.run_id,
                build_invalidate_run_payload(reason=CASCADE_INVALIDATION_REASON),
                NETWORK_ENGINEER_HEADERS,
            )
        )

        response = api_client.invalidate_test_run(
            env.run_id,
            build_invalidate_run_payload(reason="Retrying the same withdrawal"),
            NETWORK_ENGINEER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_TEST_RUN_ALREADY_INVALIDATED.value)

        assert_evidence_sample_total(
            env.reload_plan(), EVIDENCE_TOTAL_AFTER_FULL_INVALIDATION
        )


# ===========================================================================
# Temporal admissibility outranks the run's own shape
# ===========================================================================


class TestMeasurementWindowOutranksRunDuration:
    """A measurement that cannot have happened yet is refused before its shape
    is judged."""

    def test_future_measurement_window_outranks_the_exceeded_run_duration(self):
        """A future window fifteen days long surfaces the temporal complaint.

        PRD: "Four admissibility checks guard the recording, and they are decided
        in the ladder order of §2.11."

        Design: Difficulty/priority_pair_validation_conflict/measurement_window_future_outranks_run_duration_exceeded
        """
        plan, methodology, probe, _ = _measurement_world()

        response = _record_run(
            probe["id"],
            plan["id"],
            methodology["id"],
            FUTURE_LONG_WINDOW_START,
            FUTURE_LONG_WINDOW_END,
            [_sample("2026-09-06T19:10:00Z")],
        )
        validate_error(response, ApiErrorId.ERR_MEASUREMENT_WINDOW_FUTURE.value)

        assert_evidence_sample_total(
            read_service_plan(plan["id"]), REFERENCE_RUN_SAMPLE_COUNT
        )

    def test_run_duration_exceeded_surfaces_once_the_window_has_closed(self):
        """The same shape violation is reachable with the temporal rule satisfied.

        PRD: "Then the run's own shape: the span from `window_start` to
        `window_end` must not exceed the cited document's `max_run_duration_days`
        days, or the request answers `ERR_RUN_DURATION_EXCEEDED`, and every
        sample's `observed_at` must fall inside the closed interval from
        `window_start` to `window_end` inclusive, or it answers
        `ERR_SAMPLE_OUTSIDE_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/measurement_window_future_outranks_run_duration_exceeded
        """
        plan, methodology, probe, _ = _measurement_world()

        response = _record_run(
            probe["id"],
            plan["id"],
            methodology["id"],
            ADMISSIBLE_WINDOW_START,
            PAST_LONG_WINDOW_END,
            [_sample("2026-08-12T19:10:00Z")],
        )
        validate_error(response, ApiErrorId.ERR_RUN_DURATION_EXCEEDED.value)

    def test_future_window_alone_is_rejected_with_the_duration_rule_satisfied(self):
        """A one-day window entirely in the future still fails the temporal rule.

        PRD: "`window_end` must not be after the logical clock — measurement cannot
        be claimed for the future — and a future window answers
        `ERR_MEASUREMENT_WINDOW_FUTURE`."

        Design: Difficulty/priority_pair_validation_conflict/measurement_window_future_outranks_run_duration_exceeded
        """
        plan, methodology, probe, _ = _measurement_world()

        response = _record_run(
            probe["id"],
            plan["id"],
            methodology["id"],
            FUTURE_LONG_WINDOW_START,
            FUTURE_SHORT_WINDOW_END,
            [_sample("2026-09-05T19:10:00Z")],
        )
        validate_error(response, ApiErrorId.ERR_MEASUREMENT_WINDOW_FUTURE.value)

    def test_rejected_recordings_leave_the_evidence_total_at_the_accepted_runs(self):
        """Only the admissible recording moves the conserved evidence counter.

        PRD: "Recording a run recomputes the plan's `evidence_sample_total` as the
        sum of `sample_count` over that plan's runs whose `status` is `INCLUDED`,
        and increments the plan's `version`."

        Design: Difficulty/priority_pair_validation_conflict/measurement_window_future_outranks_run_duration_exceeded
        """
        plan, methodology, probe, _ = _measurement_world()

        validate_error(
            _record_run(
                probe["id"],
                plan["id"],
                methodology["id"],
                FUTURE_LONG_WINDOW_START,
                FUTURE_LONG_WINDOW_END,
                [_sample("2026-09-06T19:10:00Z")],
            ),
            ApiErrorId.ERR_MEASUREMENT_WINDOW_FUTURE.value,
        )
        validate_error(
            _record_run(
                probe["id"],
                plan["id"],
                methodology["id"],
                ADMISSIBLE_WINDOW_START,
                PAST_LONG_WINDOW_END,
                [_sample("2026-08-12T19:10:00Z")],
            ),
            ApiErrorId.ERR_RUN_DURATION_EXCEEDED.value,
        )
        validate_error(
            _record_run(
                probe["id"],
                plan["id"],
                methodology["id"],
                FUTURE_LONG_WINDOW_START,
                FUTURE_SHORT_WINDOW_END,
                [_sample("2026-09-05T19:10:00Z")],
            ),
            ApiErrorId.ERR_MEASUREMENT_WINDOW_FUTURE.value,
        )

        accepted = validate_success(
            _record_run(
                probe["id"],
                plan["id"],
                methodology["id"],
                ADMISSIBLE_WINDOW_START,
                ADMISSIBLE_WINDOW_END,
                [_sample("2026-08-11T19:10:00Z")],
            ),
            expected_status=201,
        )
        assert accepted["sample_count"] == 1, (
            f"sample_count is fixed at creation, got {accepted['sample_count']}"
        )
        assert accepted["status"] == TestRunStatus.INCLUDED.value, (
            f"a recorded run opens INCLUDED, got {accepted['status']}"
        )

        # Six samples from the reference run plus the single accepted sample; the
        # three rejected calls left the counter untouched.
        assert_evidence_sample_total(read_service_plan(plan["id"]), 7)


# ===========================================================================
# The probe cooldown buffer against probe capacity
# ===========================================================================


def _cooldown_world() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """One plan, a published methodology, a capacity-1 probe and a capacity-2
    probe, each already carrying one single-sample run over the reference
    window."""
    set_clock(REFERENCE_NOW)
    plan = create_service_plan()
    methodology = create_published_methodology()
    narrow_probe = create_measurement_probe(max_concurrent_windows=1)
    wide_probe = create_measurement_probe(max_concurrent_windows=2)
    record_test_run(
        narrow_probe["id"],
        plan["id"],
        methodology["id"],
        samples=[_sample("2026-08-03T19:10:00Z")],
    )
    record_test_run(
        wide_probe["id"],
        plan["id"],
        methodology["id"],
        samples=[_sample("2026-08-03T19:20:00Z")],
    )
    return plan, methodology, {"narrow": narrow_probe, "wide": wide_probe}


class TestProbeCooldownBufferAndCapacity:
    """The trailing 60-minute cooldown makes the buffered end inclusive, and it
    is capacity rather than geometry that decides."""

    def test_window_starting_at_the_buffered_cooldown_end_conflicts_on_a_capacity_one_probe(
        self,
    ):
        """At the buffered end the intervals still intersect; one minute later they do not.

        PRD: "Then comes the probe's aggregate capacity: count the runs on the same
        probe whose `status` is `INCLUDED` and whose measurement interval, extended
        by a trailing cooldown buffer of 60 minutes past its own `window_end`,
        intersects the requested closed interval — the two intersect when the
        requested `window_start` is at or before the other run's buffered end and
        the other run's `window_start` is at or before the requested `window_end`."

        Design: Difficulty/resource_temporal_overlap/probe_cooldown_buffer_and_capacity_boundary
        """
        plan, methodology, probes = _cooldown_world()

        at_boundary = _record_run(
            probes["narrow"]["id"],
            plan["id"],
            methodology["id"],
            BUFFERED_COOLDOWN_END,
            BOUNDARY_WINDOW_END,
            [_sample("2026-08-10T19:10:00Z")],
        )
        validate_error(at_boundary, ApiErrorId.ERR_PROBE_COOLDOWN_CONFLICT.value)

        past_boundary = validate_success(
            _record_run(
                probes["narrow"]["id"],
                plan["id"],
                methodology["id"],
                ONE_MINUTE_PAST_BUFFERED_END,
                BOUNDARY_WINDOW_END,
                [_sample("2026-08-10T19:10:00Z")],
            ),
            expected_status=201,
        )
        assert past_boundary["status"] == TestRunStatus.INCLUDED.value, (
            "a window starting strictly after the buffered end intersects nothing"
        )

    def test_the_same_boundary_geometry_is_admitted_on_a_capacity_two_probe(self):
        """Identical intervals: refused at capacity 1, accepted at capacity 2.

        PRD: "When that count reaches the probe's `max_concurrent_windows`, the
        recording is rejected with `ERR_PROBE_COOLDOWN_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/probe_cooldown_buffer_and_capacity_boundary
        """
        plan, methodology, probes = _cooldown_world()

        validate_error(
            _record_run(
                probes["narrow"]["id"],
                plan["id"],
                methodology["id"],
                BUFFERED_COOLDOWN_END,
                BOUNDARY_WINDOW_END,
                [_sample("2026-08-10T19:10:00Z")],
            ),
            ApiErrorId.ERR_PROBE_COOLDOWN_CONFLICT.value,
        )

        on_wide_probe = validate_success(
            _record_run(
                probes["wide"]["id"],
                plan["id"],
                methodology["id"],
                BUFFERED_COOLDOWN_END,
                BOUNDARY_WINDOW_END,
                [_sample("2026-08-10T19:20:00Z")],
            ),
            expected_status=201,
        )
        assert on_wide_probe["status"] == TestRunStatus.INCLUDED.value, (
            "an intersection count of 1 is below max_concurrent_windows 2"
        )

    def test_evidence_total_counts_only_the_admitted_cooldown_boundary_runs(self):
        """The refused recording contributes no samples to the plan's evidence pool.

        PRD: "Recording a run recomputes the plan's `evidence_sample_total` as the
        sum of `sample_count` over that plan's runs whose `status` is `INCLUDED`,
        and increments the plan's `version`."

        Design: Difficulty/resource_temporal_overlap/probe_cooldown_buffer_and_capacity_boundary
        """
        plan, methodology, probes = _cooldown_world()

        validate_error(
            _record_run(
                probes["narrow"]["id"],
                plan["id"],
                methodology["id"],
                BUFFERED_COOLDOWN_END,
                BOUNDARY_WINDOW_END,
                [_sample("2026-08-10T19:10:00Z")],
            ),
            ApiErrorId.ERR_PROBE_COOLDOWN_CONFLICT.value,
        )
        narrow_second = validate_success(
            _record_run(
                probes["narrow"]["id"],
                plan["id"],
                methodology["id"],
                ONE_MINUTE_PAST_BUFFERED_END,
                BOUNDARY_WINDOW_END,
                [_sample("2026-08-10T19:10:00Z")],
            ),
            expected_status=201,
        )
        wide_second = validate_success(
            _record_run(
                probes["wide"]["id"],
                plan["id"],
                methodology["id"],
                BUFFERED_COOLDOWN_END,
                BOUNDARY_WINDOW_END,
                [_sample("2026-08-10T19:20:00Z")],
            ),
            expected_status=201,
        )

        # Two setup runs plus the two accepted runs, one sample each.
        assert_evidence_sample_total(read_service_plan(plan["id"]), 4)
        assert read_test_run(narrow_second["id"])["status"] == (
            TestRunStatus.INCLUDED.value
        ), "the run past the buffered end stays INCLUDED"
        assert read_test_run(wide_second["id"])["status"] == (
            TestRunStatus.INCLUDED.value
        ), "the run on the capacity-2 probe stays INCLUDED"


# ===========================================================================
# The compensating invariant on `evidence_sample_total`
# ===========================================================================


class TestEvidenceSampleTotalCompensation:
    """Adding a run and then invalidating it is a lossless undo: the counter
    returns to its prior value and nothing downstream moves."""

    def test_invalidating_the_supplementary_run_restores_the_evidence_total_to_six(self):
        """The counter is recomputed from the rows, so the undo leaves no drift.

        PRD: "After the transition completes, the plan's `evidence_sample_total`
        equals the sum of `sample_count` over that plan's runs whose `status` is
        `INCLUDED` — exactly the value it would have had if the invalidated run had
        never been recorded, with no accumulated drift."

        Design: Difficulty/compensating_invariant/invalidate_run_restores_evidence_sample_total_invariant
        """
        env = build_reference_environment()
        assert_evidence_sample_total(env.reload_plan(), REFERENCE_RUN_SAMPLE_COUNT)

        run_b = validate_success(
            _record_run(
                env.probe_id,
                env.plan_id,
                env.methodology_id,
                SUPPLEMENTARY_WINDOW_START,
                SUPPLEMENTARY_WINDOW_END,
                [
                    _sample("2026-08-11T19:30:00Z", 244, 116, 26),
                    _sample("2026-08-11T21:15:00Z", 236, 114, 28),
                ],
            ),
            expected_status=201,
        )
        assert run_b["sample_count"] == 2, (
            f"run B carries two samples, got {run_b['sample_count']}"
        )
        assert_evidence_sample_total(env.reload_plan(), 8)

        invalidated = validate_success(
            api_client.invalidate_test_run(
                run_b["id"],
                build_invalidate_run_payload(
                    reason="Panel misconfiguration on the supplementary window"
                ),
                NETWORK_ENGINEER_HEADERS,
            )
        )
        assert invalidated["status"] == TestRunStatus.INVALIDATED.value, (
            f"run B should be INVALIDATED, got {invalidated['status']}"
        )
        plan = env.reload_plan()
        assert_evidence_sample_total(plan, REFERENCE_RUN_SAMPLE_COUNT)

        # The invariant holds exactly against the rows that back it: only run A
        # is still INCLUDED.
        runs, _meta = validate_paginated(
            api_client.list_test_runs(
                NETWORK_ENGINEER_HEADERS, params={"plan_id": env.plan_id, "limit": 100}
            )
        )
        assert_evidence_sample_total_matches_runs(plan, runs)
        included = [r for r in runs if r["status"] == TestRunStatus.INCLUDED.value]
        assert [r["id"] for r in included] == [env.run_id], (
            "run A must be the only INCLUDED run backing the restored total"
        )

    def test_the_lossless_undo_leaves_attestation_label_and_posture_untouched(self):
        """Six still clears the pinned minimum of four, so no hop of the cascade fires.

        PRD: "Every attestation of that plan whose `status` is `DRAFT` or
        `CERTIFIED` and whose pinned `min_samples_required` is now strictly greater
        than the plan's recomputed `evidence_sample_total` has its `status` set to
        `REVOKED` and its `revoked_reason` set to `EVIDENCE_BELOW_MINIMUM`."

        Design: Difficulty/compensating_invariant/invalidate_run_restores_evidence_sample_total_invariant
        """
        env = build_reference_environment()
        run_b = validate_success(
            _record_run(
                env.probe_id,
                env.plan_id,
                env.methodology_id,
                SUPPLEMENTARY_WINDOW_START,
                SUPPLEMENTARY_WINDOW_END,
                [
                    _sample("2026-08-11T19:30:00Z", 244, 116, 26),
                    _sample("2026-08-11T21:15:00Z", 236, 114, 28),
                ],
            ),
            expected_status=201,
        )
        validate_success(
            api_client.invalidate_test_run(
                run_b["id"],
                build_invalidate_run_payload(
                    reason="Panel misconfiguration on the supplementary window"
                ),
                NETWORK_ENGINEER_HEADERS,
            )
        )

        attestation = read_attestation(env.attestation_id)
        assert attestation["status"] == AttestationStatus.CERTIFIED.value, (
            f"the attestation should stay CERTIFIED, got {attestation['status']}"
        )
        assert attestation["revoked_reason"] is None, (
            "revoked_reason must stay null when the pinned minimum is still met"
        )
        assert (
            attestation["methodology_snapshot"]["min_samples_required"]
            <= REFERENCE_RUN_SAMPLE_COUNT
        ), "the pinned minimum 4 is still at or below the restored total 6"

        label = read_label(env.label_id)
        assert_label_dimensions(
            label,
            PublicationState.PUBLISHED.value,
            SubstantiationStatus.SUBSTANTIATED.value,
        )
        assert label["attestation_id"] == env.attestation_id, (
            "the label stays pinned to the same certified attestation"
        )

        assert_posture(read_service_plan(env.plan_id), LabelPosture.OPEN.value)

    def test_the_pinned_attestation_keeps_its_pooled_sample_count_throughout(self):
        """Run B never entered the existing pool, so nothing had to be recomputed.

        PRD: "The ids of exactly those runs are recorded in `included_run_ids` as a
        snapshot that is never re-derived afterwards, and the samples of those runs
        are concatenated in that same run order (and, within a run, in the order
        they appear in the `samples` array)."

        Design: Difficulty/compensating_invariant/invalidate_run_restores_evidence_sample_total_invariant
        """
        env = build_reference_environment()
        before = read_attestation(env.attestation_id)
        assert before["pooled_sample_count"] == PEAK_HOUR_MEDIAN_POOLED_COUNT, (
            f"the peak-hour pool holds {PEAK_HOUR_MEDIAN_POOLED_COUNT} samples, "
            f"got {before['pooled_sample_count']}"
        )

        run_b = validate_success(
            _record_run(
                env.probe_id,
                env.plan_id,
                env.methodology_id,
                SUPPLEMENTARY_WINDOW_START,
                SUPPLEMENTARY_WINDOW_END,
                [
                    _sample("2026-08-11T19:30:00Z", 244, 116, 26),
                    _sample("2026-08-11T21:15:00Z", 236, 114, 28),
                ],
            ),
            expected_status=201,
        )
        after_insert = read_attestation(env.attestation_id)
        assert after_insert["pooled_sample_count"] == PEAK_HOUR_MEDIAN_POOLED_COUNT, (
            "recording run B must not widen the snapshotted pool"
        )
        assert run_b["id"] not in after_insert["included_run_ids"], (
            "included_run_ids is a snapshot that is never re-derived"
        )

        validate_success(
            api_client.invalidate_test_run(
                run_b["id"],
                build_invalidate_run_payload(
                    reason="Panel misconfiguration on the supplementary window"
                ),
                NETWORK_ENGINEER_HEADERS,
            )
        )
        after_undo = read_attestation(env.attestation_id)
        assert after_undo["pooled_sample_count"] == PEAK_HOUR_MEDIAN_POOLED_COUNT, (
            "the undo is local: nothing had to be recomputed to restore the pool"
        )
        assert after_undo["included_run_ids"] == before["included_run_ids"], (
            "the run snapshot is identical before and after the compensation"
        )
