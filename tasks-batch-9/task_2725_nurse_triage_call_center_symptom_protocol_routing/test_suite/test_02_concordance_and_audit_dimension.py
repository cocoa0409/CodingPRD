"""Outcome audit: the two concordance readings and the two state dimensions."""

import pytest

from test_helpers.assertions import (
    assert_instant,
    assert_percentage,
    assert_variance,
)


@pytest.fixture
def verified_ed_now_disposition(world):
    """An in-hours ED_NOW disposition whose high-risk callback was verified."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        practice={"variance_review_threshold": 1},
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1
    )
    world.reach_and_verify(disposition["id"], "nurse_a", "nurse_c", "IMPROVED", True)
    return call, disposition


class TestConcordanceStrictVersusBandTolerant:
    def test_one_step_undertriage_scores_seven_points(
        self, world, verified_ed_now_disposition
    ):
        """PRD §3.10: "Advice of `ED_NOW` against an outcome of `ED_ADMITTED` is
        a one-step under-triage worth 7 points; advice of `ED_NOW` against
        `ED_TREATED_RELEASED` is concordant and worth zero; advice of
        `EMERGENCY_911` against `SELF_CARE_RESOLVED` is a four-step over-triage
        worth 12 points."

        Design: Difficulty/dual_variant_calc/concordance_strict_vs_band_tolerant_diverge_on_one_ordinal_gap
        """
        _, disposition = verified_ed_now_disposition
        world.set_clock("2026-08-03T19:00:00Z")

        record = world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_ADMITTED",
            outcome_observed_at="2026-08-03T18:00:00Z",
        )

        assert_variance(
            record,
            outcome_ordinal=5,
            disposition_level_ordinal=4,
            variance_class="UNDERTRIAGE",
            variance_severity_points=7,
        )

    def test_the_two_concordance_readings_diverge_on_the_same_record(
        self, world, verified_ed_now_disposition
    ):
        """PRD §3.10: "A single record with an ordinal gap of exactly one drives
        them to opposite extremes: 0.0 strict against 100.0 band-tolerant."

        Design: Difficulty/dual_variant_calc/concordance_strict_vs_band_tolerant_diverge_on_one_ordinal_gap
        """
        _, disposition = verified_ed_now_disposition
        world.set_clock("2026-08-03T19:00:00Z")
        world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_ADMITTED",
            outcome_observed_at="2026-08-03T18:00:00Z",
        )
        world.set_clock("2026-08-03T20:00:00Z")

        summary = world.compliance_summary()

        assert summary["audited_count"] == 1, "one record falls in the audit period"
        assert summary["concordant_count_strict"] == 0, (
            "the strict reading requires exactly equal ordinals"
        )
        assert summary["concordant_count_band_tolerant"] == 1, (
            "the band-tolerant reading accepts a gap of one step"
        )
        assert_percentage(
            summary["concordance_rate_strict_pct"], 0.0, "concordance_rate_strict_pct"
        )
        assert_percentage(
            summary["concordance_rate_band_tolerant_pct"],
            100.0,
            "concordance_rate_band_tolerant_pct",
        )

    def test_the_readout_reports_the_raw_material_behind_the_cascade(
        self, world, verified_ed_now_disposition
    ):
        """PRD §3.10: "The same readout reports the raw material behind the
        cascade: `undertriage_count` and `overtriage_count` as the number of
        records in that input set whose `variance_class` is `UNDERTRIAGE` and
        `OVERTRIAGE` respectively, `variance_severity_points_total` as the sum of
        `variance_severity_points` over the whole input set, and the practice's
        live `open_variance_count` and `compliance_posture` as they stand."

        Design: Difficulty/dual_variant_calc/concordance_strict_vs_band_tolerant_diverge_on_one_ordinal_gap
        """
        _, disposition = verified_ed_now_disposition
        world.set_clock("2026-08-03T19:00:00Z")
        world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_ADMITTED",
            outcome_observed_at="2026-08-03T18:00:00Z",
        )
        world.set_clock("2026-08-03T20:00:00Z")

        summary = world.compliance_summary()

        assert summary["undertriage_count"] == 1
        assert summary["overtriage_count"] == 0
        assert summary["variance_severity_points_total"] == 7
        assert summary["open_variance_count"] == 1
        assert summary["compliance_posture"] == "UNDER_REVIEW"

    def test_the_undertriage_record_escalates_the_practice(
        self, world, verified_ed_now_disposition
    ):
        """PRD §3.10: "An `UNDERTRIAGE` record advances it `OUTCOME_RECORDED →
        VARIANCE_ESCALATED` and sets off the same four-hop cascade the worsened
        callback does: the practice's `open_variance_count` increases by one;
        because that count reached the practice's `variance_review_threshold`,
        `compliance_posture` becomes `UNDER_REVIEW`".

        Design: Difficulty/dual_variant_calc/concordance_strict_vs_band_tolerant_diverge_on_one_ordinal_gap
        """
        _, disposition = verified_ed_now_disposition
        world.set_clock("2026-08-03T19:00:00Z")
        world.file_audit_record(
            disposition["id"],
            reported_outcome="ED_ADMITTED",
            outcome_observed_at="2026-08-03T18:00:00Z",
        )

        assert world.disposition(disposition["id"])["audit_status"] == (
            "VARIANCE_ESCALATED"
        ), "an under-triage record escalates the audit dimension"
        practice = world.practice()
        assert practice["open_variance_count"] == 1
        assert practice["compliance_posture"] == "UNDER_REVIEW"


@pytest.fixture
def overridden_and_reverified(world):
    """An ED_NOW disposition softened by a charge nurse, then re-verified."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_b", "nurse_c"),
        practice={"variance_review_threshold": 1},
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1
    )
    world.override_disposition(disposition["id"], "URGENT_CARE_24H", "nurse_b")
    return call, disposition


class TestAdviceAndAuditDimensionsAdvanceIndependently:
    def test_the_override_records_the_supervisor_without_touching_the_recommendation(
        self, world, overridden_and_reverified
    ):
        """PRD §3.6: "A successful override sets `final_level` to the requested
        level, sets `is_override` true, records `override_reason_code`,
        `override_narrative` and `overridden_by_nurse_id` as the acting nurse's
        identifier, moves `advice_status` to `OVERRIDDEN`, and increases both the
        disposition's `version` and the call's `version` by one each."

        Design: Difficulty/non_linear_state_machine/disposition_advice_and_audit_dimensions_advance_independently_after_override
        """
        _, disposition = overridden_and_reverified

        after = world.disposition(disposition["id"])
        assert after["advice_status"] == "OVERRIDDEN"
        assert after["recommended_level"] == "ED_NOW", (
            "recommended_level is computed by the server and is never editable"
        )
        assert after["final_level"] == "URGENT_CARE_24H"
        assert after["is_override"] is True
        assert after["overridden_by_nurse_id"] == world.nurse_id("nurse_b")
        assert after["determined_by_nurse_id"] == world.nurse_id("nurse_a")

    def test_the_softened_level_cancels_the_high_risk_task_and_raises_a_standard_one(
        self, world, overridden_and_reverified
    ):
        """PRD §3.6: "If the new level is less severe and the existing callback
        task's `status` is `PENDING`, `ATTEMPTED` or `REACHED`, that task flips to
        `CANCELLED` and the practice's `open_callback_count` decreases by one; and
        if the recomputed `requires_callback` is still true, a replacement task is
        created carrying the `risk_class`, `due_by_utc` and `max_attempts` of the
        **new** level, and `open_callback_count` increases again."

        Design: Difficulty/non_linear_state_machine/disposition_advice_and_audit_dimensions_advance_independently_after_override
        """
        _, disposition = overridden_and_reverified

        tasks = world.callbacks_for(disposition["id"])
        assert len(tasks) == 2, f"expected two callback tasks, saw {len(tasks)}"
        first, second = tasks
        assert first["status"] == "CANCELLED"
        assert first["risk_class"] == "HIGH_RISK"
        assert second["status"] == "PENDING"
        assert second["risk_class"] == "STANDARD"
        assert second["max_attempts"] == 2
        assert_instant(
            second["due_by_utc"], "2026-08-04T02:30:00Z", "replacement due_by_utc"
        )
        assert world.practice()["open_callback_count"] == 1, (
            "one cancellation and one creation leave exactly one open task"
        )

    def test_the_audit_dimension_closes_quietly_against_the_final_level(
        self, world, overridden_and_reverified
    ):
        """PRD §3.10: "`disposition_level_ordinal` is the severity of the
        disposition's `final_level` — never its `recommended_level` — captured at
        the moment the record was filed, on the same five-point scale defined in
        Section 3.6."

        Design: Difficulty/non_linear_state_machine/disposition_advice_and_audit_dimensions_advance_independently_after_override
        """
        _, disposition = overridden_and_reverified
        world.reach_and_verify(disposition["id"], "nurse_a", "nurse_c", "IMPROVED", True)
        world.set_clock("2026-08-03T16:00:00Z")

        record = world.file_audit_record(
            disposition["id"],
            reported_outcome="URGENT_CARE_VISIT",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T15:40:00Z",
        )

        assert_variance(
            record,
            outcome_ordinal=3,
            disposition_level_ordinal=3,
            variance_class="CONCORDANT",
            variance_severity_points=0,
        )
        audited = world.disposition(disposition["id"])
        assert audited["audit_status"] == "CONCORDANT_CLOSED", (
            "a concordant record is terminal and quiet"
        )
        assert audited["advice_status"] == "OVERRIDDEN", (
            "the advice dimension is untouched by the audit dimension"
        )

    def test_a_concordant_close_leaves_every_practice_variance_counter_at_zero(
        self, world, overridden_and_reverified
    ):
        """PRD §3.10: "An `OVERTRIAGE` record does neither: it leaves the audit
        dimension resting at `OUTCOME_RECORDED`, escalates nothing, and touches no
        practice counter. Only under-triage escalates."

        Design: Difficulty/non_linear_state_machine/disposition_advice_and_audit_dimensions_advance_independently_after_override
        """
        _, disposition = overridden_and_reverified
        world.reach_and_verify(disposition["id"], "nurse_a", "nurse_c", "IMPROVED", True)
        world.set_clock("2026-08-03T16:00:00Z")
        world.file_audit_record(
            disposition["id"],
            reported_outcome="URGENT_CARE_VISIT",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T15:40:00Z",
        )

        practice = world.practice()
        assert practice["open_callback_count"] == 0
        assert practice["escalated_callback_count"] == 0
        assert practice["compliance_posture"] == "NORMAL"
        assert world.compliance_summary()["open_variance_count"] == 0
