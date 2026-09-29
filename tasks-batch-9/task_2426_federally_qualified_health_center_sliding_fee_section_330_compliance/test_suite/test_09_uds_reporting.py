"""Computing the annual report: per-measure rounding and the income distribution."""

import pytest

from test_helpers import (
    OFFICER,
    api_client,
    compute_uds_report,
    same_instant,
    setup_boot_fs,
    setup_draft_uds_report,
    setup_encounter,
    setup_quality_measure,
    setup_verified_patient,
    validate_success,
)


def _report_with_three_measures():
    """One reported patient at exactly 100 percent and three measures awaiting compute."""
    ctx = setup_boot_fs()
    verified = setup_verified_patient(
        ctx,
        mrn="MRN-001",
        full_name="Ada Rivera",
        household_size=2,
        declared_annual_income_cents=2190000,
    )
    setup_encounter(
        ctx,
        verified["patient_id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=12000,
    )
    report = setup_draft_uds_report(ctx, reporting_year=2026)
    diabetes = setup_quality_measure(
        report, measure_code="DIABETES_A1C", numerator=7, denominator=9, benchmark_pct=77.8
    )
    hypertension = setup_quality_measure(
        report, measure_code="HYPERTENSION", numerator=1, denominator=3, benchmark_pct=40.0
    )
    dental = setup_quality_measure(
        report, measure_code="DENTAL_SEALANT", numerator=0, denominator=0, benchmark_pct=50.0
    )
    ctx.update(
        {
            "verified": verified,
            "report": report,
            "diabetes": diabetes,
            "hypertension": hypertension,
            "dental": dental,
        }
    )
    return ctx


def _measure(measure_id):
    return validate_success(api_client.get_quality_measure_result(measure_id, OFFICER))


def test_each_measure_is_rounded_first_and_the_zero_denominator_one_is_excluded():
    """Per-measure rates round to one decimal and an empty population is excluded.

    PRD 3.9: "For a measure whose `denominator` is 0, `rate_pct` is null,
    `inclusion_status` is `EXCLUDED_ZERO_DENOMINATOR` and `meets_benchmark` is null —
    a measure with no eligible population is excluded rather than scored as zero. For
    every other measure, `rate_pct` is the `numerator` divided by the `denominator`,
    multiplied by 100, rounded half up to one decimal place; `inclusion_status` is
    `INCLUDED`; and `meets_benchmark` is true when the rounded `rate_pct` is greater
    than or equal to `benchmark_pct`, so a rate exactly equal to the benchmark meets
    it."

    Design: Difficulty/combinatorial_formula/uds_composite_round_per_measure_then_average_mode_b
    """
    ctx = _report_with_three_measures()

    computed = compute_uds_report(ctx["report"])

    diabetes = _measure(ctx["diabetes"]["id"])
    assert diabetes["rate_pct"] == pytest.approx(77.8, abs=0.01), (
        f"7 of 9 is 77.777… which rounds to 77.8, got {diabetes['rate_pct']}"
    )
    assert diabetes["inclusion_status"] == "INCLUDED"
    assert diabetes["meets_benchmark"] is True, (
        "a rate exactly equal to the benchmark meets it"
    )

    hypertension = _measure(ctx["hypertension"]["id"])
    assert hypertension["rate_pct"] == pytest.approx(33.3, abs=0.01)
    assert hypertension["inclusion_status"] == "INCLUDED"
    assert hypertension["meets_benchmark"] is False

    dental = _measure(ctx["dental"]["id"])
    assert dental["rate_pct"] is None
    assert dental["inclusion_status"] == "EXCLUDED_ZERO_DENOMINATOR"
    assert dental["meets_benchmark"] is None

    assert computed["included_measure_count"] == 2, (
        "the excluded measure leaves the divisor, got "
        f"{computed['included_measure_count']}"
    )


def test_the_composite_averages_the_already_rounded_rates_rather_than_pooling_them():
    """The pinned order of operations produces a different number from pooling.

    PRD 3.9: "Otherwise `composite_quality_rate_pct` is the sum of the included
    measures' `rate_pct` values divided by `included_measure_count`, rounded half up
    to one decimal place. The order of operations is pinned: each measure is rounded
    first and the already-rounded rates are then averaged. Pooling the numerators and
    denominators of all measures and computing a single rate is explicitly *not* this
    system's composite, and produces a different number from the same data."

    Design: Difficulty/combinatorial_formula/uds_composite_round_per_measure_then_average_mode_b
    """
    ctx = _report_with_three_measures()
    assert ctx["verified"]["income_verification"]["uds_fpg_percent"] == pytest.approx(
        100.00, abs=0.01
    )

    computed = compute_uds_report(ctx["report"])

    assert computed["composite_quality_rate_pct"] == pytest.approx(55.6, abs=0.01), (
        "the mean of 77.8 and 33.3 is 55.55, which rounds half up to 55.6, got "
        f"{computed['composite_quality_rate_pct']}"
    )
    assert computed["composite_quality_rate_pct"] != pytest.approx(66.7, abs=0.01), (
        "pooling 8 over 12 would have given 66.7, which is not this system's composite"
    )
    assert computed["total_patient_count"] == 1
    assert computed["patients_at_or_below_100_count"] == 1, (
        "an intake-year percentage at or below 100.00 lands in the lowest band"
    )
    assert computed["unverified_patient_count"] == 0
    assert same_instant(computed["computed_at"]) == "2026-08-01T00:00:00Z", (
        "computing stamps computed_at with the logical clock"
    )
