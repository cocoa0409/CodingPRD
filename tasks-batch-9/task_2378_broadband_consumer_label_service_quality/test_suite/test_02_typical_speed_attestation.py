"""Typical-speed attestations: variant pooling, certification thresholds and pool cardinality.

The scenarios here all live on `POST /performance-attestations` and
`POST /performance-attestations/{id}/certify`: how the two documented metric
variants pool the very same measurement rows, which of the two certification
preconditions surfaces when both are violated, and what happens at the two
boundaries the PRD pins — a download margin landing exactly on the 0.80 floor
and a peak-hour pool of exactly zero samples.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_evidence_sample_total,
    assert_margins,
    assert_optional_timestamp_absent,
    assert_optional_timestamp_present,
    assert_posture,
)
from test_helpers.constants import (
    ALL_HOUR_P20_DOWNLOAD_MARGIN,
    ALL_HOUR_P20_POOLED_COUNT,
    ALL_HOUR_P20_TYPICAL_DOWNLOAD,
    ALL_HOUR_P20_TYPICAL_LATENCY,
    ALL_HOUR_P20_TYPICAL_UPLOAD,
    ALL_HOUR_P20_UPLOAD_MARGIN,
    PEAK_HOUR_MEDIAN_DOWNLOAD_MARGIN,
    PEAK_HOUR_MEDIAN_POOLED_COUNT,
    PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
    PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
    PEAK_HOUR_MEDIAN_UPLOAD_MARGIN,
    REFERENCE_NOW,
)
from test_helpers.factories import build_attestation_payload, build_sample
from test_helpers.fixtures import (
    create_attestation,
    create_measurement_probe,
    create_published_methodology,
    create_reference_plan,
    create_service_plan,
    current_plan_version,
    read_attestation,
    read_service_plan,
    record_test_run,
    set_clock,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, NETWORK_ENGINEER_HEADERS
from test_helpers.types import (
    AttestationStatus,
    LabelPosture,
    MetricVariant,
    Technology,
)

# ---------------------------------------------------------------------------
# Pre-computed expectations that no shared constant already carries.
# ---------------------------------------------------------------------------

#: The thin evidence pool of the low-margin plan: three peak-hour samples.
THIN_POOLED_COUNT = 3
#: The same plan once a second run has lifted the peak-hour pool over the minimum.
FAT_POOLED_COUNT = 5
LOW_MARGIN_TYPICAL_DOWNLOAD = 100.00
LOW_MARGIN_TYPICAL_UPLOAD = 40.00
LOW_MARGIN_TYPICAL_LATENCY = 90
LOW_MARGIN_DOWNLOAD_MARGIN = 0.3333
LOW_MARGIN_UPLOAD_MARGIN = 0.2857
LOW_MARGIN_EVIDENCE_TOTAL = 5

#: 240 / 301 = 0.797342... rounded half up to four decimal places.
EDGE_ADVERTISED_DOWNLOAD_MBPS = 301
EDGE_DOWNLOAD_MARGIN = 0.7973

#: Three off-peak observations only, so the peak pool is empty and the
#: all-hours pool picks nearest rank ceil(0.20 * 3) == 1.
OFF_PEAK_POOLED_COUNT = 3
OFF_PEAK_TYPICAL_DOWNLOAD = 120.00
OFF_PEAK_TYPICAL_UPLOAD = 40.00
OFF_PEAK_TYPICAL_LATENCY = 50
OFF_PEAK_DOWNLOAD_MARGIN = 0.4000
OFF_PEAK_UPLOAD_MARGIN = 0.2857


def _typical(attestation, field):
    """Typical speed figures are two-decimal numbers; compare them as floats."""
    return float(attestation[field])


# ---------------------------------------------------------------------------
# World builders
#
# Each builder positions the logical clock first, since every measurement
# window and every `*_at` timestamp reads it, and then builds only the rows its
# own scenario needs.
# ---------------------------------------------------------------------------


def _build_shared_run_pool_world():
    """A fibre plan advertising 300/140 with one six-sample run — four of the
    six inside the 19:00-23:00 peak band — and a DRAFT peak-hour attestation."""
    set_clock(REFERENCE_NOW)
    plan = create_service_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    run = record_test_run(probe["id"], plan["id"], methodology["id"])
    peak_attestation = create_attestation(
        plan["id"],
        methodology["id"],
        metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
    )
    return {
        "plan_id": plan["id"],
        "methodology_id": methodology["id"],
        "run_id": run["id"],
        "peak_attestation_id": peak_attestation["id"],
    }


def _create_all_hour_variant(api, world):
    """The trigger of the shared-pool scenario: a second attestation over the
    identical run pool, this time under the all-hours algorithm."""
    payload = build_attestation_payload(
        world["plan_id"],
        world["methodology_id"],
        current_plan_version(world["plan_id"]),
        metric_variant=MetricVariant.ALL_HOUR_P20.value,
    )
    return api.create_performance_attestation(payload, NETWORK_ENGINEER_HEADERS)


_LOW_MARGIN_SAMPLE_VALUES = (100, 40, 90)


def _low_margin_sample(observed_at):
    download, upload, latency = _LOW_MARGIN_SAMPLE_VALUES
    return build_sample(observed_at, download, upload, latency)


def _build_thin_pool_world():
    """A plan whose only run carries three peak-hour samples, so the pool is one
    sample short of the methodology minimum *and* far below the margin floor."""
    set_clock(REFERENCE_NOW)
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    plan = create_service_plan(
        display_name="Rural 300",
        technology=Technology.FIXED_WIRELESS.value,
        monthly_price_cents=6999,
        early_termination_fee_cents=0,
    )
    first_run = record_test_run(
        probe["id"],
        plan["id"],
        methodology["id"],
        window_start="2026-08-03T00:00:00Z",
        window_end="2026-08-05T00:00:00Z",
        samples=[
            _low_margin_sample("2026-08-03T19:00:00Z"),
            _low_margin_sample("2026-08-04T20:00:00Z"),
            _low_margin_sample("2026-08-04T21:00:00Z"),
        ],
    )
    thin_attestation = create_attestation(
        plan["id"],
        methodology["id"],
        metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
    )
    return {
        "plan_id": plan["id"],
        "methodology_id": methodology["id"],
        "probe_id": probe["id"],
        "first_run_id": first_run["id"],
        "thin_attestation_id": thin_attestation["id"],
    }


def _widen_the_pool(world):
    """Record a second run of two more peak-hour samples and attest over both,
    lifting the pool to five so only the margin rule can still bite."""
    second_run = record_test_run(
        world["probe_id"],
        world["plan_id"],
        world["methodology_id"],
        window_start="2026-08-06T00:00:00Z",
        window_end="2026-08-07T00:00:00Z",
        samples=[
            _low_margin_sample("2026-08-06T19:00:00Z"),
            _low_margin_sample("2026-08-06T22:00:00Z"),
        ],
    )
    fat_attestation = create_attestation(
        world["plan_id"],
        world["methodology_id"],
        metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
    )
    return second_run, fat_attestation


_BOUNDARY_SAMPLE_VALUES = (
    ("19:10:00", 210, 100, 42),
    ("21:30:00", 238, 112, 24),
    ("20:40:00", 242, 118, 22),
    ("19:45:00", 290, 130, 18),
    ("14:30:00", 295, 145, 14),
    ("02:40:00", 306, 155, 55),
)

_EDGE_SAMPLE_DAYS = (
    "2026-08-11",
    "2026-08-12",
    "2026-08-13",
    "2026-08-16",
    "2026-08-13",
    "2026-08-14",
)


def _build_margin_boundary_world():
    """Two plans measured on the identical six sample values: one advertising
    300 Mbps down, where the median lands exactly on the floor, and one
    advertising 301 Mbps, where it rounds just below."""
    set_clock(REFERENCE_NOW)

    plan = create_reference_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    record_test_run(probe["id"], plan["id"], methodology["id"])
    attestation = create_attestation(
        plan["id"],
        methodology["id"],
        metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
    )

    edge_plan = create_service_plan(
        display_name="Fiber 301",
        advertised_download_mbps=EDGE_ADVERTISED_DOWNLOAD_MBPS,
        early_termination_fee_cents=0,
    )
    edge_probe = create_measurement_probe(max_concurrent_windows=1)
    record_test_run(
        edge_probe["id"],
        edge_plan["id"],
        methodology["id"],
        window_start="2026-08-11T00:00:00Z",
        window_end="2026-08-17T23:00:00Z",
        samples=[
            build_sample(f"{day}T{clock_time}Z", download, upload, latency)
            for day, (clock_time, download, upload, latency) in zip(
                _EDGE_SAMPLE_DAYS, _BOUNDARY_SAMPLE_VALUES
            )
        ],
    )
    edge_attestation = create_attestation(
        edge_plan["id"],
        methodology["id"],
        metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
    )

    return {
        "attestation_id": attestation["id"],
        "edge_attestation_id": edge_attestation["id"],
    }


def _build_off_peak_only_world():
    """A plan whose only run was measured entirely at 14:00 UTC, so no
    observation falls inside the 19:00-23:00 peak band."""
    set_clock(REFERENCE_NOW)
    methodology = create_published_methodology()
    probe = create_measurement_probe(max_concurrent_windows=1)
    plan = create_service_plan(
        display_name="Cable 300",
        technology=Technology.CABLE.value,
        monthly_price_cents=5999,
        early_termination_fee_cents=0,
    )
    run = record_test_run(
        probe["id"],
        plan["id"],
        methodology["id"],
        window_start="2026-08-03T00:00:00Z",
        window_end="2026-08-05T00:00:00Z",
        samples=[
            build_sample("2026-08-03T14:00:00Z", 150, 50, 40),
            build_sample("2026-08-04T14:00:00Z", 120, 40, 30),
            build_sample("2026-08-04T14:30:00Z", 180, 60, 50),
        ],
    )
    return {
        "plan_id": plan["id"],
        "methodology_id": methodology["id"],
        "run_id": run["id"],
        "plan_version": current_plan_version(plan["id"]),
    }


# ---------------------------------------------------------------------------
# Design: Difficulty/dual_variant_calc/typical_speed_variants_diverge_on_identical_run_pool
# ---------------------------------------------------------------------------


class TestTypicalSpeedVariantsOnOneRunPool:
    """Both documented algorithms read one run and disclose different figures."""

    def test_all_hour_variant_pools_every_sample_of_the_shared_run(self, api):
        """The all-hours variant pools all six observations, peak or not.

        PRD: "Under `ALL_HOUR_P20` — the conservative all-hours floor cited in the
        methodology annex — every sample is pooled regardless of hour."

        Design: Difficulty/dual_variant_calc/typical_speed_variants_diverge_on_identical_run_pool
        """
        world = _build_shared_run_pool_world()

        response = _create_all_hour_variant(api, world)

        p20 = validate_success(response, expected_status=201)
        assert p20["pooled_sample_count"] == ALL_HOUR_P20_POOLED_COUNT, (
            "the all-hours pool is every sample of the run, not only the "
            f"peak-hour ones: expected {ALL_HOUR_P20_POOLED_COUNT}"
        )
        assert _typical(p20, "typical_download_mbps") == pytest.approx(
            ALL_HOUR_P20_TYPICAL_DOWNLOAD, abs=0.01
        )
        assert _typical(p20, "typical_upload_mbps") == pytest.approx(
            ALL_HOUR_P20_TYPICAL_UPLOAD, abs=0.01
        )
        assert p20["typical_latency_ms"] == ALL_HOUR_P20_TYPICAL_LATENCY, (
            "the ninety-fifth-percentile latency of the all-hours pool is "
            f"{ALL_HOUR_P20_TYPICAL_LATENCY} ms"
        )
        assert_margins(
            p20, ALL_HOUR_P20_DOWNLOAD_MARGIN, ALL_HOUR_P20_UPLOAD_MARGIN
        )

    def test_the_two_variants_diverge_on_the_identical_run_pool(self, api):
        """One run, two algorithms, two different typical-speed claims.

        PRD: "For `PEAK_HOUR_MEDIAN`, `typical_download_mbps` is the median of the
        pooled `download_mbps` values and `typical_upload_mbps` the median of the
        pooled `upload_mbps` values: sort the values ascending, take the single
        central value when the count is odd, and take the arithmetic mean of the two
        central values when the count is even."

        Design: Difficulty/dual_variant_calc/typical_speed_variants_diverge_on_identical_run_pool
        """
        world = _build_shared_run_pool_world()

        p20 = validate_success(
            _create_all_hour_variant(api, world), expected_status=201
        )
        peak = read_attestation(world["peak_attestation_id"])

        assert peak["pooled_sample_count"] == PEAK_HOUR_MEDIAN_POOLED_COUNT, (
            "only the four peak-window observations enter the peak-hour pool"
        )
        assert _typical(peak, "typical_download_mbps") == pytest.approx(
            PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD, abs=0.01
        )
        assert _typical(peak, "typical_upload_mbps") == pytest.approx(
            PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD, abs=0.01
        )
        assert peak["typical_latency_ms"] == PEAK_HOUR_MEDIAN_TYPICAL_LATENCY
        assert_margins(
            peak,
            PEAK_HOUR_MEDIAN_DOWNLOAD_MARGIN,
            PEAK_HOUR_MEDIAN_UPLOAD_MARGIN,
        )

        assert peak["included_run_ids"] == [world["run_id"]], (
            "the peak-hour attestation snapshots the single eligible run"
        )
        assert p20["included_run_ids"] == [world["run_id"]], (
            "the all-hours attestation snapshots exactly the same run"
        )
        assert _typical(p20, "typical_download_mbps") < _typical(
            peak, "typical_download_mbps"
        ), "on identical run data the all-hours variant yields the lower download figure"
        assert p20["typical_latency_ms"] > peak["typical_latency_ms"], (
            "the all-hours pool carries the off-peak observations, so its "
            "ninety-fifth-percentile latency is the higher of the two"
        )

    def test_creating_the_all_hour_variant_leaves_its_draft_sibling_alone(self, api):
        """Superseding only ever displaces a *certified* attestation.

        PRD: "Creating an attestation for a plan that already has a certified
        attestation is legitimate and supersedes it: the older attestation's `status`
        moves from `CERTIFIED` to `SUPERSEDED` — by invariant there is at most one
        certified attestation per plan — while any label already pinned to the
        superseded attestation keeps its pinned typical figures and its
        `substantiation_status` untouched, because a published label discloses what it
        disclosed."

        Design: Difficulty/dual_variant_calc/typical_speed_variants_diverge_on_identical_run_pool
        """
        world = _build_shared_run_pool_world()

        validate_success(_create_all_hour_variant(api, world), expected_status=201)

        peak = read_attestation(world["peak_attestation_id"])
        assert peak["status"] == AttestationStatus.DRAFT.value, (
            "the peak-hour sibling was never certified, so nothing supersedes it"
        )
        assert_optional_timestamp_absent(peak, "certified_at")
        assert peak["revoked_reason"] is None, "no revocation happened"


# ---------------------------------------------------------------------------
# Design: Difficulty/priority_pair_validation_conflict/insufficient_samples_outranks_substantiation_margin
# ---------------------------------------------------------------------------


class TestInsufficientSamplesOutranksSubstantiationMargin:
    """Evidence sufficiency is judged before evidence quality on certification."""

    def test_thin_pool_reports_the_sample_count_not_the_margin(self, api):
        """Both certification rules are violated; the count rule answers first.

        PRD: "**Evidence sufficiency.** On creating an attestation and on certifying
        one — otherwise `ERR_NO_ELIGIBLE_TEST_RUNS` or `ERR_INSUFFICIENT_SAMPLES`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/insufficient_samples_outranks_substantiation_margin
        """
        world = _build_thin_pool_world()
        thin = read_attestation(world["thin_attestation_id"])
        assert thin["pooled_sample_count"] == THIN_POOLED_COUNT, (
            "the pool is one sample short of the pinned minimum of four"
        )
        assert_margins(thin, LOW_MARGIN_DOWNLOAD_MARGIN, LOW_MARGIN_UPLOAD_MARGIN)

        response = api.certify_performance_attestation(
            world["thin_attestation_id"], COMPLIANCE_OFFICER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SAMPLES.value)

        unchanged = read_attestation(world["thin_attestation_id"])
        assert unchanged["status"] == AttestationStatus.DRAFT.value, (
            "a rejected certification leaves the attestation in DRAFT"
        )
        assert unchanged["pooled_sample_count"] == THIN_POOLED_COUNT
        assert round(float(unchanged["download_margin_pct"]), 4) == (
            LOW_MARGIN_DOWNLOAD_MARGIN
        ), "the margin problem is real but was never the reported failure"

    def test_margin_becomes_visible_once_the_pool_is_large_enough(self, api):
        """With five samples the count rule passes and the margin rule answers.

        PRD: "It requires that the attestation still be `DRAFT`, or the request
        answers `ERR_ATTESTATION_INVALID_STATE`; that `pooled_sample_count` be at
        least the pinned `min_samples_required`, with an inclusive boundary, or the
        request answers `ERR_INSUFFICIENT_SAMPLES`; and that both
        `download_margin_pct` and `upload_margin_pct` be at least 0.80 — again an
        inclusive boundary, so exactly 0.8000 passes — or the request answers
        `ERR_SUBSTANTIATION_MARGIN_NOT_MET`."

        Design: Difficulty/priority_pair_validation_conflict/insufficient_samples_outranks_substantiation_margin
        """
        world = _build_thin_pool_world()
        validate_error(
            api.certify_performance_attestation(
                world["thin_attestation_id"], COMPLIANCE_OFFICER_HEADERS
            ),
            ApiErrorId.ERR_INSUFFICIENT_SAMPLES.value,
        )
        _second_run, fat = _widen_the_pool(world)

        assert fat["pooled_sample_count"] == FAT_POOLED_COUNT, (
            "the widened pool concatenates both runs' peak-hour samples"
        )
        assert _typical(fat, "typical_download_mbps") == pytest.approx(
            LOW_MARGIN_TYPICAL_DOWNLOAD, abs=0.01
        )
        assert _typical(fat, "typical_upload_mbps") == pytest.approx(
            LOW_MARGIN_TYPICAL_UPLOAD, abs=0.01
        )
        assert fat["typical_latency_ms"] == LOW_MARGIN_TYPICAL_LATENCY
        assert_margins(fat, LOW_MARGIN_DOWNLOAD_MARGIN, LOW_MARGIN_UPLOAD_MARGIN)

        response = api.certify_performance_attestation(
            fat["id"], COMPLIANCE_OFFICER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_SUBSTANTIATION_MARGIN_NOT_MET.value)

        refused = read_attestation(fat["id"])
        assert refused["status"] == AttestationStatus.DRAFT.value, (
            "the margin rejection left the attestation in DRAFT"
        )
        assert_optional_timestamp_absent(refused, "certified_at")

    def test_neither_refused_certification_moved_the_plan_off_restricted(self, api):
        """The plan keeps its recomputed evidence total and its posture.

        PRD: "Otherwise, if the plan has no published label at all, the posture is
        `RESTRICTED`."

        Design: Difficulty/priority_pair_validation_conflict/insufficient_samples_outranks_substantiation_margin
        """
        world = _build_thin_pool_world()
        validate_error(
            api.certify_performance_attestation(
                world["thin_attestation_id"], COMPLIANCE_OFFICER_HEADERS
            ),
            ApiErrorId.ERR_INSUFFICIENT_SAMPLES.value,
        )
        _second_run, fat = _widen_the_pool(world)
        validate_error(
            api.certify_performance_attestation(fat["id"], COMPLIANCE_OFFICER_HEADERS),
            ApiErrorId.ERR_SUBSTANTIATION_MARGIN_NOT_MET.value,
        )

        plan = read_service_plan(world["plan_id"])

        assert_evidence_sample_total(plan, LOW_MARGIN_EVIDENCE_TOTAL)
        assert_posture(plan, LabelPosture.RESTRICTED.value)


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/substantiation_margin_exactly_eighty_percent_passes
# ---------------------------------------------------------------------------


class TestSubstantiationMarginAtTheFloor:
    """A one-unit change in the advertised denominator flips the verdict."""

    def test_margin_exactly_at_the_floor_certifies(self, api):
        """240.00 against 300 Mbps is 0.8000, which the inclusive floor admits.

        PRD: "It requires that the attestation still be `DRAFT`, or the request
        answers `ERR_ATTESTATION_INVALID_STATE`; that `pooled_sample_count` be at
        least the pinned `min_samples_required`, with an inclusive boundary, or the
        request answers `ERR_INSUFFICIENT_SAMPLES`; and that both
        `download_margin_pct` and `upload_margin_pct` be at least 0.80 — again an
        inclusive boundary, so exactly 0.8000 passes — or the request answers
        `ERR_SUBSTANTIATION_MARGIN_NOT_MET`."

        Design: Difficulty/boundary_precision_check/substantiation_margin_exactly_eighty_percent_passes
        """
        world = _build_margin_boundary_world()
        draft = read_attestation(world["attestation_id"])
        assert_margins(
            draft,
            PEAK_HOUR_MEDIAN_DOWNLOAD_MARGIN,
            PEAK_HOUR_MEDIAN_UPLOAD_MARGIN,
        )

        response = api.certify_performance_attestation(
            world["attestation_id"], COMPLIANCE_OFFICER_HEADERS
        )

        certified = validate_success(response)
        assert certified["status"] == AttestationStatus.CERTIFIED.value, (
            "a download margin of exactly 0.8000 clears the floor"
        )
        assert_optional_timestamp_present(certified, "certified_at")
        assert certified["certified_at"].startswith("2026-09-01T00:00:00"), (
            "certified_at is taken from the logical clock, positioned at "
            f"{REFERENCE_NOW}"
        )

    def test_margin_rounding_just_below_the_floor_is_refused(self, api):
        """The same measurement against 301 Mbps rounds to 0.7973 and fails.

        PRD: "`download_margin_pct` is `typical_download_mbps` divided by the plan's
        `advertised_download_mbps`, and `upload_margin_pct` is `typical_upload_mbps`
        divided by `advertised_upload_mbps`, each rounded half up to four decimal
        places."

        Design: Difficulty/boundary_precision_check/substantiation_margin_exactly_eighty_percent_passes
        """
        world = _build_margin_boundary_world()
        edge = read_attestation(world["edge_attestation_id"])
        assert _typical(edge, "typical_download_mbps") == pytest.approx(
            PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD, abs=0.01
        ), "the pooled median is the same 240.00 Mbps as on the 300 Mbps plan"
        assert round(float(edge["download_margin_pct"]), 4) == EDGE_DOWNLOAD_MARGIN, (
            "240 divided by 301 rounds half up to four decimals as "
            f"{EDGE_DOWNLOAD_MARGIN}"
        )

        response = api.certify_performance_attestation(
            world["edge_attestation_id"], COMPLIANCE_OFFICER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_SUBSTANTIATION_MARGIN_NOT_MET.value)

        refused = read_attestation(world["edge_attestation_id"])
        assert refused["status"] == AttestationStatus.DRAFT.value, (
            "the attestation stays in DRAFT when the margin is not met"
        )
        assert_optional_timestamp_absent(refused, "certified_at")

    def test_both_attestations_clear_the_sample_count_so_only_the_margin_differs(
        self, api
    ):
        """Four pooled samples on either side, so the count rule is not in play.

        PRD: "`pooled_sample_count` is the number of samples in the resulting pool,
        and an empty pool is likewise rejected with `ERR_NO_ELIGIBLE_TEST_RUNS`; this
        is the case where runs exist but none of their observations fall inside the
        peak window."

        Design: Difficulty/boundary_precision_check/substantiation_margin_exactly_eighty_percent_passes
        """
        world = _build_margin_boundary_world()

        for attestation_id in (world["attestation_id"], world["edge_attestation_id"]):
            attestation = read_attestation(attestation_id)
            assert attestation["pooled_sample_count"] == PEAK_HOUR_MEDIAN_POOLED_COUNT, (
                "both plans were measured on the same four peak-window "
                "observations, so the sample-count precondition is satisfied twice"
            )


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/variant_sample_pool_at_zero_cardinality
# ---------------------------------------------------------------------------


class TestVariantSamplePoolAtZeroCardinality:
    """A peak-hour pool of exactly zero samples versus an all-hours pool of three."""

    def test_empty_peak_window_pool_is_refused_at_creation(self, api):
        """Every observation sits at 14:00 UTC, below the 19:00 peak start.

        PRD: "Under `PEAK_HOUR_MEDIAN` — the busy-hour claim the label's
        typical-speed line cites — only samples whose `observed_at` falls in the
        pinned peak window are pooled: the UTC hour of the observation must be at or
        after `peak_hours_start_utc_hour` and strictly before
        `peak_hours_end_utc_hour`."

        Design: Difficulty/boundary_precision_check/variant_sample_pool_at_zero_cardinality
        """
        world = _build_off_peak_only_world()

        response = api.create_performance_attestation(
            build_attestation_payload(
                world["plan_id"],
                world["methodology_id"],
                world["plan_version"],
                metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
            ),
            NETWORK_ENGINEER_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_TEST_RUNS.value)

    def test_all_hour_pool_of_three_picks_the_minimum_by_nearest_rank(self, api):
        """The all-hours variant pools the same three rows and ranks them.

        PRD: "For `ALL_HOUR_P20`, both figures are the nearest-rank twentieth
        percentile of the corresponding pooled values: sort ascending and take the
        value whose one-based rank is the pool size multiplied by 0.20 and then
        rounded up to the next whole number."

        Design: Difficulty/boundary_precision_check/variant_sample_pool_at_zero_cardinality
        """
        world = _build_off_peak_only_world()
        validate_error(
            api.create_performance_attestation(
                build_attestation_payload(
                    world["plan_id"],
                    world["methodology_id"],
                    world["plan_version"],
                    metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
                ),
                NETWORK_ENGINEER_HEADERS,
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_TEST_RUNS.value,
        )

        response = api.create_performance_attestation(
            build_attestation_payload(
                world["plan_id"],
                world["methodology_id"],
                world["plan_version"],
                metric_variant=MetricVariant.ALL_HOUR_P20.value,
            ),
            NETWORK_ENGINEER_HEADERS,
        )

        attestation = validate_success(response, expected_status=201)
        assert attestation["pooled_sample_count"] == OFF_PEAK_POOLED_COUNT, (
            "the all-hours pool takes every observation regardless of hour"
        )
        assert attestation["included_run_ids"] == [world["run_id"]], (
            "the snapshot names the single eligible run"
        )
        assert _typical(attestation, "typical_download_mbps") == pytest.approx(
            OFF_PEAK_TYPICAL_DOWNLOAD, abs=0.01
        ), "nearest rank one selects the minimum of the three downloads"
        assert _typical(attestation, "typical_upload_mbps") == pytest.approx(
            OFF_PEAK_TYPICAL_UPLOAD, abs=0.01
        ), "nearest rank one selects the minimum of the three uploads"
        assert attestation["typical_latency_ms"] == OFF_PEAK_TYPICAL_LATENCY, (
            "the ninety-fifth-percentile rank over three samples is the third, "
            "so the worst latency is reported"
        )
        assert_margins(
            attestation, OFF_PEAK_DOWNLOAD_MARGIN, OFF_PEAK_UPLOAD_MARGIN
        )
