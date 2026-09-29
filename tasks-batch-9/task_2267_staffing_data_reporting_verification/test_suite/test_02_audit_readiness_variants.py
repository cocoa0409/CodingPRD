"""Sampled versus full-population audit readiness over one stored quarter."""

from test_helpers import (
    AuditReadinessVariant,
    approx_hours,
    approx_ratio,
    approx_score,
    assert_audit_readiness_read,
    validate_success,
)


class TestAuditReadinessVariants:
    def test_01_sampled_reading_truncates_to_the_first_five_entries_by_work_date(
        self, api, audit_sample_quarter, reading_auditor_headers
    ):
        """PRD: "The sampled reading, which is the one acceptance uses, takes the
        first 5 `ACTIVE` hour entries of the submission ordered by `work_date`
        ascending with `created_at` ascending as the tie-break." The 2026-04-06
        shift falls outside the sample, so only 48.00 of the 60.00 hours are
        considered and only 20.00 of the 32.00 supported hours count.

        Design: Difficulty/dual_variant_calc/audit_support_score_sampled_vs_full_population
        """
        scenario = audit_sample_quarter
        data = validate_success(
            api.get_audit_readiness(
                scenario.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": scenario.id,
                    "variant": AuditReadinessVariant.SAMPLED.value,
                },
            )
        )

        assert_audit_readiness_read(data, AuditReadinessVariant.SAMPLED.value)
        assert data["considered_entry_count"] == 5
        assert data["considered_hours"] == approx_hours(48.00)
        assert data["supported_hours"] == approx_hours(20.00)
        assert data["support_ratio"] == approx_ratio(0.4167)

    def test_02_sampled_reading_scores_below_the_risk_floor(
        self, api, audit_sample_quarter, reading_auditor_headers
    ):
        """PRD: "The score is then 100 multiplied by the sum of the support ratio
        weighted at 0.50, the vendor attestation ratio weighted at 0.30, and the
        census reconciled ratio weighted at 0.20, with that single product
        rounded half up to 2 decimal places." With no vendor-sourced hours the
        attestation ratio takes its 1.0000 empty-set value and two of the three
        census days are RECONCILED, so the sampled score is 64.17.

        Design: Difficulty/dual_variant_calc/audit_support_score_sampled_vs_full_population
        """
        scenario = audit_sample_quarter
        data = validate_success(
            api.get_audit_readiness(
                scenario.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": scenario.id,
                    "variant": AuditReadinessVariant.SAMPLED.value,
                },
            )
        )

        assert data["vendor_attestation_ratio"] == approx_ratio(1.0000)
        assert data["census_reconciled_ratio"] == approx_ratio(0.6667)
        assert data["score"] == approx_score(64.17)
        assert data["at_risk"] is True

    def test_03_full_reading_takes_every_active_entry_and_lands_exactly_on_the_floor(
        self, api, audit_sample_quarter, reading_auditor_headers
    ):
        """PRD: "The full reading takes every `ACTIVE` hour entry of the
        submission, with no truncation and therefore no dependence on ordering."
        All six entries give 60.00 considered and 32.00 supported hours, and
        "A submission is at risk when the score is strictly below 70.00, so a
        score of exactly 70.00 is not at risk."

        Design: Difficulty/dual_variant_calc/audit_support_score_sampled_vs_full_population
        """
        scenario = audit_sample_quarter
        data = validate_success(
            api.get_audit_readiness(
                scenario.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": scenario.id,
                    "variant": AuditReadinessVariant.FULL.value,
                },
            )
        )

        assert_audit_readiness_read(data, AuditReadinessVariant.FULL.value)
        assert data["considered_entry_count"] == 6
        assert data["considered_hours"] == approx_hours(60.00)
        assert data["supported_hours"] == approx_hours(32.00)
        assert data["support_ratio"] == approx_ratio(0.5333)
        assert data["score"] == approx_score(70.00)
        assert data["at_risk"] is False

    def test_04_the_two_readings_diverge_by_sample_truncation_alone(
        self, api, audit_sample_quarter, reading_auditor_headers
    ):
        """PRD: "The two readings differ only in the considered set." Identical
        stored data therefore yields 70.00 in full and 64.17 sampled, a
        divergence of 5.83 score points that flips the at-risk verdict.

        Design: Difficulty/dual_variant_calc/audit_support_score_sampled_vs_full_population
        """
        scenario = audit_sample_quarter
        sampled = validate_success(
            api.get_audit_readiness(
                scenario.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": scenario.id,
                    "variant": AuditReadinessVariant.SAMPLED.value,
                },
            )
        )
        full = validate_success(
            api.get_audit_readiness(
                scenario.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": scenario.id,
                    "variant": AuditReadinessVariant.FULL.value,
                },
            )
        )

        assert float(full["score"]) - float(sampled["score"]) == approx_score(5.83)
        assert sampled["at_risk"] is True
        assert full["at_risk"] is False

    def test_05_omitting_the_variant_selects_the_sampled_reading(
        self, api, audit_sample_quarter, reading_auditor_headers
    ):
        """PRD: "it takes a `submission_id` and an optional `variant`, where
        omitting the variant or passing `SAMPLED` selects the sampled reading and
        passing `FULL` selects the full one".

        Design: Difficulty/dual_variant_calc/audit_support_score_sampled_vs_full_population
        """
        scenario = audit_sample_quarter
        data = validate_success(
            api.get_audit_readiness(
                scenario.facility_id,
                reading_auditor_headers,
                {"submission_id": scenario.id},
            )
        )

        assert data["variant"] == AuditReadinessVariant.SAMPLED.value
        assert data["considered_entry_count"] == 5
        assert data["score"] == approx_score(64.17)
