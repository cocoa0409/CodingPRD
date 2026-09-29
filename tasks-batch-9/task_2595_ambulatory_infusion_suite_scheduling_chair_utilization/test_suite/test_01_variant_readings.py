"""Two-variant computed reads: chair utilization and the no-show risk figure."""

import pytest

from test_helpers import (
    ApiClient,
    BookingClass,
    ChairType,
    ReminderTier,
    RiskVariant,
    ScheduleStatus as SS,
    SteeringStatus,
    UtilizationVariant,
    add_patient_with_plan,
    book_appointment,
    confirm_visit,
    create_chair,
    inject_history,
    read_appointment,
    read_no_show_risk,
    read_patient,
    read_utilization,
    setup_approved_authorization,
    setup_suite,
)


def _utilization_estate(api: ApiClient):
    """Four AVAILABLE chairs, one completed visit with realised minutes and one
    live CONFIRMED add-on that has never been sat in."""
    suite = setup_suite(
        api,
        clock="2026-08-10T13:00:00Z",
        chair_labels=("A1", "A2", "A3"),
        drug_kind="gate",
    )
    create_chair(
        api,
        suite.center_id,
        "U1",
        chair_type=ChairType.ISOLATION,
        reserved_for_urgent=True,
    )
    completed = inject_history(
        api,
        suite.center_id,
        suite.patient_id,
        suite.plan_id,
        suite.template_id,
        service_date="2026-08-10",
        schedule_status=SS.COMPLETED,
        chair_minutes=240,
        start_minute=510,
        actual_start_minute=510,
        actual_end_minute=760,
        cycle_number=1,
    )
    patient2, plan2 = add_patient_with_plan(api, suite, "MRN-0002", "Pat Two")
    live = book_appointment(
        api,
        suite.center_id,
        patient2["id"],
        plan2["id"],
        suite.template_id,
        service_date="2026-08-10",
        requested_start_minute=840,
        cycle_number=1,
        booking_class=BookingClass.SAME_DAY_ADDON,
    )
    setup_approved_authorization(api, live["id"])
    live = confirm_visit(api, live["id"])
    return suite, completed, live


class TestChairUtilizationVariants:
    """The denominator is shared; only the numerator parts company."""

    def test_scheduled_variant_attributes_planned_chair_minutes(self, api):
        """The SCHEDULED numerator sums planned chair_minutes over both live and
        completed work, so a completed visit contributes its planned length rather
        than the length it actually ran.

        Design: Difficulty/dual_variant_calc/chair_utilization_scheduled_vs_actual_variant_divergence
        """
        suite, _completed, _live = _utilization_estate(api)

        report = read_utilization(
            api, suite.center_id, "2026-08-10", UtilizationVariant.SCHEDULED
        )

        assert report["variant"] == UtilizationVariant.SCHEDULED
        assert report["available_chair_minutes"] == 2640
        assert report["occupied_chair_minutes"] == 480
        assert report["utilization_pct"] == pytest.approx(18.18, abs=0.005)
        assert report["appointment_count"] == 2
        assert report["biosimilar_savings_cents"] == 0

    def test_actual_variant_attributes_only_realised_minutes(self, api):
        """The ACTUAL numerator asks how long each chair was really occupied, so the
        completed visit contributes 760 - 510 and the never-seated visit contributes
        nothing at all.

        Design: Difficulty/dual_variant_calc/chair_utilization_scheduled_vs_actual_variant_divergence
        """
        suite, _completed, _live = _utilization_estate(api)

        report = read_utilization(
            api, suite.center_id, "2026-08-10", UtilizationVariant.ACTUAL
        )

        assert report["variant"] == UtilizationVariant.ACTUAL
        assert report["available_chair_minutes"] == 2640
        assert report["occupied_chair_minutes"] == 250
        assert report["utilization_pct"] == pytest.approx(9.47, abs=0.005)
        # PRD 3.10: appointment_count is "the number of that day's visits at that
        # centre to which the chosen variant attributed a length". Under ACTUAL the
        # never-seated CONFIRMED visit "contributes nothing", so only the COMPLETED
        # visit is attributed a length.
        assert report["appointment_count"] == 1
        assert report["biosimilar_savings_cents"] == 0

    def test_confirmed_visit_is_the_source_of_the_variant_divergence(self, api):
        """One dataset, two readings: the CONFIRMED row carries no actual_start_minute,
        which is exactly why it contributes 240 under SCHEDULED and 0 under ACTUAL.

        Design: Difficulty/dual_variant_calc/chair_utilization_scheduled_vs_actual_variant_divergence
        """
        suite, _completed, live = _utilization_estate(api)

        row = read_appointment(api, live["id"])
        assert row["schedule_status"] == SS.CONFIRMED
        assert row["actual_start_minute"] is None
        assert row["chair_minutes"] == 240

        scheduled = read_utilization(
            api, suite.center_id, "2026-08-10", UtilizationVariant.SCHEDULED
        )
        actual = read_utilization(
            api, suite.center_id, "2026-08-10", UtilizationVariant.ACTUAL
        )
        assert (
            scheduled["occupied_chair_minutes"] - actual["occupied_chair_minutes"] == 230
        )
        assert scheduled["available_chair_minutes"] == actual["available_chair_minutes"]


def _adherence_history(api: ApiClient):
    """Three terminal visits inside Q3 2026: two COMPLETED and one NO_SHOW."""
    suite = setup_suite(api, clock="2026-08-05T07:00:00Z", drug_kind="gate")
    for cycle, (service_date, status) in enumerate(
        [
            ("2026-07-06", SS.COMPLETED),
            ("2026-07-20", SS.COMPLETED),
            ("2026-08-03", SS.NO_SHOW),
        ],
        start=1,
    ):
        extra = {}
        if status == SS.COMPLETED:
            extra = {"actual_start_minute": 540, "actual_end_minute": 780}
        inject_history(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=service_date,
            schedule_status=status,
            chair_minutes=240,
            start_minute=540,
            cycle_number=cycle,
            **extra,
        )
    return suite


class TestNoShowRiskVariants:
    """The recency-weighted reading and the payer-facing quarter reading diverge."""

    def test_rolling6_variant_is_recency_weighted(self, api):
        """The most recent row carries weight 100 and each successive row 15 less, so
        the lone NO_SHOW contributes 100 of a 255 weight total.

        Design: Difficulty/dual_variant_calc/no_show_risk_rolling6_vs_quarter_to_date_variant_divergence
        """
        suite = _adherence_history(api)

        result = read_no_show_risk(api, suite.patient_id, RiskVariant.ROLLING_6)

        assert result["patient_id"] == suite.patient_id
        assert result["variant"] == RiskVariant.ROLLING_6
        assert result["score"] == pytest.approx(39.22, abs=0.005)
        assert result["reminder_tier"] == ReminderTier.ELEVATED
        assert result["considered_appointment_count"] == 3

    def test_quarter_to_date_variant_is_unweighted(self, api):
        """The quarter reading is the count of NO_SHOW visits over the count of visits
        in the quarter, so the identical three rows give one in three.

        Design: Difficulty/dual_variant_calc/no_show_risk_rolling6_vs_quarter_to_date_variant_divergence
        """
        suite = _adherence_history(api)

        result = read_no_show_risk(api, suite.patient_id, RiskVariant.QUARTER_TO_DATE)

        assert result["variant"] == RiskVariant.QUARTER_TO_DATE
        assert result["score"] == pytest.approx(33.33, abs=0.005)
        assert result["considered_appointment_count"] == 3

    def test_persisted_score_mirrors_the_rolling_variant_only(self, api):
        """reminder_tier is always derived from the ROLLING_6 score and never from the
        quarter figure, and the persisted field obeys the same rule.

        Design: Difficulty/dual_variant_calc/no_show_risk_rolling6_vs_quarter_to_date_variant_divergence
        """
        suite = _adherence_history(api)

        patient = read_patient(api, suite.patient_id)

        assert patient["no_show_risk_score"] == pytest.approx(39.22, abs=0.005)
        assert patient["reminder_tier"] == ReminderTier.ELEVATED
        assert patient["no_show_strikes"] == 1
        assert patient["completed_appointment_count"] == 2
        assert patient["steering_status"] == SteeringStatus.SUITE

    def test_rolling_variant_is_the_default_reading(self, api):
        """The optional variant defaults to ROLLING_6.

        Design: Difficulty/dual_variant_calc/no_show_risk_rolling6_vs_quarter_to_date_variant_divergence
        """
        suite = _adherence_history(api)

        result = read_no_show_risk(api, suite.patient_id)

        assert result["variant"] == RiskVariant.ROLLING_6
        assert result["score"] == pytest.approx(39.22, abs=0.005)
