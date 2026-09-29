"""The two readings of hours per resident day over one stored quarter."""

from test_helpers import (
    HprdVariant,
    approx_hours,
    approx_ratio,
    assert_hprd_read,
    validate_success,
)


class TestHprdVariantDivergence:
    def test_01_as_submitted_reading_counts_every_active_hour_over_reported_census(
        self, api, dual_variant_quarter
    ):
        """PRD: "Under the as-submitted reading, the numerator population is
        every hour entry of the submission whose `entry_status` is `ACTIVE`,
        regardless of `verification_status`, and each counted census day
        contributes its facility-reported `resident_count`." All four 15.00-hour
        RN shifts count, giving 60.00 direct-care hours over the 15 reported
        resident days of the three counted census days.

        Design: Difficulty/dual_variant_calc/hprd_as_submitted_vs_audit_adjusted_divergence
        """
        scenario = dual_variant_quarter
        data = validate_success(
            api.get_submission_hprd(
                scenario.id,
                scenario.universe.coord_headers,
                {"variant": HprdVariant.AS_SUBMITTED.value},
            )
        )

        assert_hprd_read(data, HprdVariant.AS_SUBMITTED.value)
        assert data["total_direct_care_hours"] == approx_hours(60.00)
        assert data["resident_days"] == 15
        assert data["total_nurse_hprd"] == approx_ratio(4.0000)
        assert data["rn_hprd"] == approx_ratio(4.0000)

    def test_02_as_submitted_weekend_figures_use_the_weekend_census_days_only(
        self, api, dual_variant_quarter
    ):
        """PRD: "`weekend_total_nurse_hprd` is the weekend direct-care hours
        divided by the weekend denominator, rounded half up to 4 decimal places,
        or null when the weekend denominator is 0." Only the Saturday
        2026-04-04 shift and census day are weekend rows, so 15.00 weekend hours
        fall over 5 weekend resident days.

        Design: Difficulty/dual_variant_calc/hprd_as_submitted_vs_audit_adjusted_divergence
        """
        scenario = dual_variant_quarter
        data = validate_success(
            api.get_submission_hprd(
                scenario.id,
                scenario.universe.coord_headers,
                {"variant": HprdVariant.AS_SUBMITTED.value},
            )
        )

        assert data["weekend_direct_care_hours"] == approx_hours(15.00)
        assert data["weekend_resident_days"] == 5
        assert data["weekend_total_nurse_hprd"] == approx_ratio(3.0000)

    def test_03_audit_adjusted_reading_drops_unverified_hours_and_substitutes_mds_counts(
        self, api, dual_variant_quarter
    ):
        """PRD: "Under the audit-adjusted reading, the numerator population is
        narrowed to active entries whose `verification_status` is `SUPPORTED` —
        unverified and unsupported hours are dropped entirely — and each counted
        census day contributes its `mds_resident_count` when that is non-null and
        its `resident_count` otherwise." Only the two verified shifts survive
        (30.00 hours) and the denominator becomes 5 + 5 + 6 = 16.

        Design: Difficulty/dual_variant_calc/hprd_as_submitted_vs_audit_adjusted_divergence
        """
        scenario = dual_variant_quarter
        data = validate_success(
            api.get_submission_hprd(
                scenario.id,
                scenario.universe.coord_headers,
                {"variant": HprdVariant.AUDIT_ADJUSTED.value},
            )
        )

        assert_hprd_read(data, HprdVariant.AUDIT_ADJUSTED.value)
        assert data["total_direct_care_hours"] == approx_hours(30.00)
        assert data["resident_days"] == 16
        assert data["total_nurse_hprd"] == approx_ratio(1.8750)
        assert data["rn_hprd"] == approx_ratio(1.8750)
        assert data["weekend_direct_care_hours"] == approx_hours(0.00)
        assert data["weekend_resident_days"] == 6
        assert data["weekend_total_nurse_hprd"] == approx_ratio(0.0000)

    def test_04_the_two_readings_diverge_on_identical_stored_data(
        self, api, dual_variant_quarter
    ):
        """PRD: "Hours per resident day is the central published metric, and it
        is computed twice from the same submission under two different
        readings." Both numerator filter and denominator source differ, so the
        same quarter answers 4.0000 as submitted and 1.8750 audit-adjusted.

        Design: Difficulty/dual_variant_calc/hprd_as_submitted_vs_audit_adjusted_divergence
        """
        scenario = dual_variant_quarter
        as_submitted = validate_success(
            api.get_submission_hprd(
                scenario.id,
                scenario.universe.coord_headers,
                {"variant": HprdVariant.AS_SUBMITTED.value},
            )
        )
        audit_adjusted = validate_success(
            api.get_submission_hprd(
                scenario.id,
                scenario.universe.coord_headers,
                {"variant": HprdVariant.AUDIT_ADJUSTED.value},
            )
        )

        divergence = float(as_submitted["total_nurse_hprd"]) - float(
            audit_adjusted["total_nurse_hprd"]
        )
        assert divergence == approx_ratio(2.1250)
        assert as_submitted["variant"] != audit_adjusted["variant"]

    def test_05_omitting_the_variant_selects_the_as_submitted_reading(
        self, api, dual_variant_quarter
    ):
        """PRD: "The read takes an optional `variant` query parameter; omitting
        it or passing `AS_SUBMITTED` selects the as-submitted reading and passing
        `AUDIT_ADJUSTED` selects the audit-adjusted one."

        Design: Difficulty/dual_variant_calc/hprd_as_submitted_vs_audit_adjusted_divergence
        """
        scenario = dual_variant_quarter
        data = validate_success(
            api.get_submission_hprd(scenario.id, scenario.universe.coord_headers)
        )

        assert data["variant"] == HprdVariant.AS_SUBMITTED.value
        assert data["total_nurse_hprd"] == approx_ratio(4.0000)
        assert data["implausible"] is False
