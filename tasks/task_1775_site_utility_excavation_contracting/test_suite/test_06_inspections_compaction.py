"""Installation inspection results and backfill compaction arithmetic."""

import pytest

from test_helpers import (
    FOREMAN,
    ApiErrorId,
    get_segment,
    record_accepted_pass_test,
    record_compaction_test,
    record_installation_inspection,
    review_compaction_test,
    setup_backfilling_segment,
    setup_installed_segment,
    validate_error,
    validate_success,
)


def test_inspection_slope_tolerance_boundary(api):
    """PRD §3.4: "The computed `result` is `PASS` only when bedding and joints
    both conform, the measured slope deviates from the segment's
    `design_slope_pct` by at most 0.2 percentage points with the boundary
    inclusive, and the cover is at least 0.5 feet; anything else is `FAIL`."

    Design: Corner/calculations/inspection_slope_tolerance_boundary
    """
    ctx = setup_installed_segment(shallow=False)  # design_slope_pct == 1.0
    segment_id = ctx["segment"]["id"]

    at_boundary = record_installation_inspection(
        segment_id, slope_measured_pct=1.2
    )
    assert at_boundary["result"] == "PASS", (
        f"|1.2 - 1.0| == 0.2 <= 0.2 must pass, got {at_boundary['result']}"
    )

    beyond = record_installation_inspection(segment_id, slope_measured_pct=1.21)
    assert beyond["result"] == "FAIL", (
        f"|1.21 - 1.0| == 0.21 > 0.2 must fail, got {beyond['result']}"
    )


def test_compaction_exactly_at_required_passes(api):
    """PRD §3.4: "The computed `compaction_pct` is one hundred times the field
    density divided by the proctor maximum, rounded half up to one decimal
    place. The `required_pct` depends on the segment's bedding class — 95.0
    for `CLASS_B`, 90.0 for `CLASS_C`, 85.0 for `CLASS_D` — and the `result`
    is `PASS` when the compaction percentage is at least the required
    percentage, boundary inclusive, and `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/compaction_exactly_at_required_passes
    """
    ctx = setup_backfilling_segment(shallow=False)  # CLASS_B -> required 95.0
    segment_id = ctx["segment"]["id"]

    at_boundary = record_compaction_test(
        segment_id, 1, proctor_max_density_pcf=150.0, field_density_pcf=142.5,
    )
    assert at_boundary["compaction_pct"] == pytest.approx(95.0, abs=1e-9)
    assert at_boundary["required_pct"] == pytest.approx(95.0, abs=1e-9)
    assert at_boundary["result"] == "PASS"

    below = record_compaction_test(
        segment_id, 2, proctor_max_density_pcf=150.0, field_density_pcf=142.4,
    )
    assert below["compaction_pct"] == pytest.approx(94.9, abs=1e-9)
    assert below["result"] == "FAIL"


def test_compaction_boundary_on_class_c(api):
    """PRD §3.4: "The computed `compaction_pct` is one hundred times the field
    density divided by the proctor maximum, rounded half up to one decimal
    place. The `required_pct` depends on the segment's bedding class — 95.0
    for `CLASS_B`, 90.0 for `CLASS_C`, 85.0 for `CLASS_D` — and the `result`
    is `PASS` when the compaction percentage is at least the required
    percentage, boundary inclusive, and `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/compaction_exactly_at_required_passes
    """
    ctx = setup_backfilling_segment(
        shallow=True, segment_overrides={"bedding_class": "CLASS_C"}
    )  # CLASS_C -> required 90.0
    segment_id = ctx["segment"]["id"]

    at_boundary = record_compaction_test(
        segment_id, 1, proctor_max_density_pcf=150.0, field_density_pcf=135.0,
    )
    assert at_boundary["compaction_pct"] == pytest.approx(90.0, abs=1e-9)
    assert at_boundary["required_pct"] == pytest.approx(90.0, abs=1e-9)
    assert at_boundary["result"] == "PASS"

    below = record_compaction_test(
        segment_id, 2, proctor_max_density_pcf=150.0, field_density_pcf=134.9,
    )
    assert below["compaction_pct"] == pytest.approx(89.9, abs=1e-9)
    assert below["result"] == "FAIL"


def test_compaction_summary_mean_vs_worst_lift(api):
    """PRD §3.4: "the segment's tests in `ACCEPTED` status only, with
    `RECORDED` and `REJECTED` excluded: `lifts_satisfied` becomes the count of
    distinct lift numbers between 1 and `lifts_required` that hold an accepted
    passing test; `avg_compaction_pct` becomes the arithmetic mean of
    `compaction_pct` across the governing set, rounded half up to one decimal;
    and `min_compaction_pct` becomes the lowest value in that set."

    Design: Difficulty/dual_variant_calc/segment_compaction_mean_vs_worst_lift
    """
    ctx = setup_backfilling_segment(shallow=False)  # CLASS_B -> required 95.0
    segment_id = ctx["segment"]["id"]

    ct1 = record_accepted_pass_test(
        segment_id, 1, proctor=150.0, field=142.5
    )
    ct2 = record_accepted_pass_test(
        segment_id, 2, proctor=150.0, field=143.5
    )
    assert ct1["compaction_pct"] == pytest.approx(95.0, abs=1e-9)
    assert ct2["compaction_pct"] == pytest.approx(95.7, abs=1e-9)

    segment = get_segment(segment_id)
    assert segment["lifts_satisfied"] == 2
    # MEAN variant: round_half_up((95.0 + 95.7) / 2, 1) == 95.4
    assert segment["avg_compaction_pct"] == pytest.approx(95.4, abs=1e-9)
    # WORST_LIFT variant over the identical governing set.
    assert segment["min_compaction_pct"] == pytest.approx(95.0, abs=1e-9)
    assert segment["avg_compaction_pct"] != segment["min_compaction_pct"]


def test_compaction_summary_excludes_unreviewed_tests(api):
    """PRD §3.4: "the segment's tests in `ACCEPTED` status only, with
    `RECORDED` and `REJECTED` excluded: `lifts_satisfied` becomes the count of
    distinct lift numbers between 1 and `lifts_required` that hold an accepted
    passing test; `avg_compaction_pct` becomes the arithmetic mean of
    `compaction_pct` across the governing set, rounded half up to one decimal;
    and `min_compaction_pct` becomes the lowest value in that set."

    Design: Difficulty/dual_variant_calc/segment_compaction_mean_vs_worst_lift
    """
    ctx = setup_backfilling_segment(shallow=False)  # CLASS_B -> required 95.0
    segment_id = ctx["segment"]["id"]

    ct1 = record_accepted_pass_test(segment_id, 1, proctor=150.0, field=142.5)
    assert ct1["status"] == "ACCEPTED"

    # Second test stays RECORDED — it must not enter the governing set.
    ct2 = record_compaction_test(
        segment_id, 2, proctor_max_density_pcf=150.0, field_density_pcf=143.5,
    )
    assert ct2["status"] == "RECORDED"

    segment = get_segment(segment_id)
    assert segment["lifts_satisfied"] == 1
    assert segment["avg_compaction_pct"] == pytest.approx(95.0, abs=1e-9)
    assert segment["min_compaction_pct"] == pytest.approx(95.0, abs=1e-9)


def test_lift_sequence_enforced(api):
    """PRD §3.4: "Tests may only be recorded while the segment is
    `BACKFILLING` (`ERR_INVALID_STATE` otherwise), and lift numbering is
    strictly sequential: each test's `lift_number` must equal the highest lift
    number already recorded or accepted on the segment plus one, with the
    first test numbered 1, else `ERR_LIFT_SEQUENCE`."

    Design: Corner/validations/lift_sequence_enforced
    """
    ctx = setup_backfilling_segment()  # shallow 2-lift segment
    segment_id = ctx["segment"]["id"]

    response = api.create_compaction_test(
        {
            "pipe_segment_id": segment_id, "lift_number": 2,
            "proctor_max_density_pcf": 100.0, "field_density_pcf": 90.0,
            "moisture_pct": 10.0,
        },
        FOREMAN,
    )
    validate_error(response, ApiErrorId.ERR_LIFT_SEQUENCE, 422)


def test_complete_with_missing_lifts_rejected(api):
    """PRD §3.4: "Completion then moves `BACKFILLING → COMPLETE` only when
    `lifts_satisfied` equals `lifts_required` (`ERR_LIFTS_INCOMPLETE`
    otherwise): the gate is per-lift worst-lift coverage, not the average, so
    a healthy `avg_compaction_pct` can never mask a missing lift."

    Design: Corner/validations/complete_with_missing_lifts_rejected
    """
    ctx = setup_backfilling_segment()  # shallow 2-lift segment
    segment_id = ctx["segment"]["id"]
    record_accepted_pass_test(segment_id, 1)  # 90.0 >= 85.0 -> PASS, ACCEPTED

    segment = get_segment(segment_id)
    assert segment["lifts_satisfied"] == 1
    assert segment["lifts_required"] == 2

    response = api.complete_segment(segment_id, FOREMAN)
    validate_error(response, ApiErrorId.ERR_LIFTS_INCOMPLETE, 409)
    segment = get_segment(segment_id)
    assert segment["status"] == "BACKFILLING"
    assert segment["lifts_satisfied"] == 1
