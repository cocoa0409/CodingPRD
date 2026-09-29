"""Nested window arithmetic, the pinned billing rounding order, and the share tier
whose selector key is the provisional total."""

import pytest

from test_helpers import (
    ApiClient,
    BookingClass,
    DoseTier,
    LotStatus,
    PreparationStatus,
    ReminderTier,
    ScheduleStatus,
    SteeringStatus,
    add_patient_with_plan,
    book_appointment,
    compound_dose,
    create_lot,
    create_patient,
    create_plan,
    create_template,
    create_floored_drug,
    inject_history,
    read_appointment,
    read_chair,
    read_chair_billing,
    read_lot,
    read_nurse,
    read_patient,
    read_preparation,
    read_template,
    request_dose,
    set_clock,
    setup_suite,
    validate_success,
)
from test_helpers import SCHEDULER


class TestWindowBuildNestedMax:
    """admin_minutes is the larger of the floor and the escalated base, in that order."""

    def _two_product_suite(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-05T07:00:00Z",
            chair_labels=("A1", "A2"),
            drug_kind="gate",
            drug_overrides={"requires_lab_gate": False, "lab_min_anc": None,
                            "lab_min_platelets": None},
        )
        slow_drug = create_floored_drug(api)
        slow_template = create_template(
            api, suite.center_id, slow_drug["id"], DoseTier.LOW
        )
        first = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        patient2 = create_patient(api, "MRN-0002", "Pat Two")
        plan2 = create_plan(
            api,
            patient2["id"],
            slow_drug["id"],
            dose_mg_per_kg=5,
            total_cycles=4,
        )
        second = book_appointment(
            api,
            suite.center_id,
            patient2["id"],
            plan2["id"],
            slow_template["id"],
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        return suite, slow_template, first, second

    def test_tier_escalation_lifts_the_push_time_over_the_floor(self, api):
        """For the 700 mg MID dose the escalated base 120 + 30 beats the floor 90, so
        the push runs 150 minutes and the chair window is 30 + 150 + 60.

        Design: Difficulty/combinatorial_formula/window_build_nested_max_over_tiered_admin_leg_mode_a
        """
        _suite, _slow_template, first, _second = self._two_product_suite(api)

        assert first["admin_minutes"] == 150
        assert first["premed_minutes"] == 30
        assert first["observation_minutes"] == 60
        assert first["chair_minutes"] == 240
        assert first["acuity_points"] == 3
        assert first["start_minute"] == 540
        assert first["end_minute"] == 780

    def test_outer_floor_wins_over_the_inner_tiered_value(self, api):
        """The floor is applied over the escalated value, so a LOW-tier dose of the
        slow product still runs its 150-minute floor rather than the tiered 60 + 0.

        Design: Difficulty/combinatorial_formula/window_build_nested_max_over_tiered_admin_leg_mode_a
        """
        _suite, _slow_template, _first, second = self._two_product_suite(api)

        assert second["admin_minutes"] == 150
        assert second["premed_minutes"] == 20
        assert second["observation_minutes"] == 45
        assert second["chair_minutes"] == 215, (
            "20 + 150 + 45 == 215; applying the floor before the tier add gives 125"
        )
        assert second["chair_minutes"] != 125
        assert second["acuity_points"] == 2
        assert second["start_minute"] == 540
        assert second["end_minute"] == 755

    def test_templates_snapshot_acuity_and_stagger_offset(self, api):
        """A LOW or MID template takes the drug's own acuity, and a template below the
        doubling threshold carries the plain grid width as its stagger offset.

        Design: Difficulty/combinatorial_formula/window_build_nested_max_over_tiered_admin_leg_mode_a
        """
        suite, slow_template, _first, _second = self._two_product_suite(api)

        mid = read_template(api, suite.template_id)
        assert mid["acuity_points"] == 2
        assert mid["stagger_offset_minutes"] == 15

        low = read_template(api, slow_template["id"])
        assert low["acuity_points"] == 1
        assert low["stagger_offset_minutes"] == 15

    def test_both_windows_land_on_distinct_chairs_and_load_one_nurse(self, api):
        """The second booking cannot share chair A1 at 540, so it takes A2, and the two
        derived load figures carry each visit's own contribution.

        Design: Difficulty/combinatorial_formula/window_build_nested_max_over_tiered_admin_leg_mode_a
        """
        suite, _slow_template, first, second = self._two_product_suite(api)

        assert first["chair_id"] == suite.chair_id("A1")
        assert second["chair_id"] == suite.chair_id("A2")
        assert second["nurse_id"] == suite.nurse_id

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_chair(api, suite.chair_id("A2"))["committed_minutes"] == 215
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 5


class TestBillableUnitRoundingOrder:
    """Each visit is ceilinged to a whole quarter-hour first, and only then summed."""

    def _billing_day(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-10T20:00:00Z",
            drug_kind="gate",
            drug_overrides={"requires_lab_gate": False, "lab_min_anc": None,
                            "lab_min_platelets": None},
        )
        patient2, plan2 = add_patient_with_plan(api, suite, "MRN-0002", "Pat Two")
        long_visit = inject_history(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            schedule_status=ScheduleStatus.COMPLETED,
            chair_minutes=240,
            start_minute=510,
            actual_start_minute=510,
            actual_end_minute=760,
            cycle_number=1,
        )
        short_visit = inject_history(
            api,
            suite.center_id,
            patient2["id"],
            plan2["id"],
            suite.template_id,
            service_date="2026-08-10",
            schedule_status=ScheduleStatus.COMPLETED,
            chair_minutes=240,
            start_minute=600,
            actual_start_minute=600,
            actual_end_minute=692,
            cycle_number=1,
        )
        return suite, long_visit, short_visit

    def test_each_visit_is_ceilinged_to_a_whole_quarter_hour(self, api):
        """A 250-minute occupancy bills 17 units and a 92-minute one bills 7, because
        each visit's partial quarter-hour is billable on its own.

        Design: Difficulty/combinatorial_formula/billable_units_ceiling_per_appointment_then_summed_mode_b
        """
        _suite, long_visit, short_visit = self._billing_day(api)

        assert read_appointment(api, long_visit["id"])["billable_chair_units"] == 17
        assert read_appointment(api, short_visit["id"])["billable_chair_units"] == 7

    def test_day_total_sums_the_already_rounded_figures(self, api):
        """Rounding each visit up first and then summing gives 24 units; summing the raw
        minutes and rounding once would under-bill at 23.

        Design: Difficulty/combinatorial_formula/billable_units_ceiling_per_appointment_then_summed_mode_b
        """
        suite, _long_visit, _short_visit = self._billing_day(api)

        summary = read_chair_billing(api, suite.center_id, "2026-08-10")

        assert summary["center_id"] == suite.center_id
        assert summary["service_date"] == "2026-08-10"
        assert summary["completed_appointment_count"] == 2
        assert summary["day_billable_units"] == 24
        assert summary["day_billable_units"] != 23
        assert summary["day_billable_cents"] == 216000
        assert summary["day_billable_cents"] != 207000


class TestCancellationShareTierSelectorKey:
    """The patient's share tier is looked up on the provisional total."""

    def _late_cancellation(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-05T07:00:00Z",
            drug_kind="ungated",
            dose_tier=DoseTier.LOW,
            plan_overrides={"dose_mg_per_kg": 5, "total_cycles": 4},
        )
        lot = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-A",
            units_received=10,
            expires_on="2026-12-01T00:00:00Z",
        )
        appointment = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
            booking_class=BookingClass.ROUTINE,
        )
        prep = request_dose(api, appointment["id"], 2)
        set_clock(api, "2026-08-10T08:30:00Z")
        prep = compound_dose(api, prep["id"])
        response = api.cancel_appointment(
            appointment["id"], SCHEDULER, {"reason": "Patient reported fever this morning"}
        )
        cancelled = validate_success(response, 200)
        return suite, lot, appointment, prep, cancelled

    def test_share_tier_reads_the_provisional_total_not_the_waste_alone(self, api):
        """The provisional total 2500 + 24000 sits above the 25,000-cent edge, so the
        share is 35 percent and the charge is 2500 + 8400.

        Design: Difficulty/combinatorial_formula/cancellation_charge_share_tier_keyed_on_provisional_total_mode_c
        """
        _suite, _lot, _appointment, _prep, cancelled = self._late_cancellation(api)

        assert cancelled["schedule_status"] == ScheduleStatus.CANCELLED
        assert cancelled["late_cancellation"] is True
        assert cancelled["cancellation_charge_cents"] == 10900
        assert cancelled["cancellation_charge_cents"] != 7300, (
            "7300 is what keying the tier on the waste figure alone would produce"
        )

    def test_the_cancelled_window_and_its_wasted_dose_are_priced_together(self, api):
        """The LOW-tier window runs 0 + 60 + 30 minutes and the dose this cancellation
        wasted is priced at units_requested multiplied by the unit cost.

        Design: Difficulty/combinatorial_formula/cancellation_charge_share_tier_keyed_on_provisional_total_mode_c
        """
        _suite, _lot, _appointment, prep, cancelled = self._late_cancellation(api)

        assert cancelled["chair_minutes"] == 90
        assert cancelled["start_minute"] == 540
        assert cancelled["end_minute"] == 630

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.WASTED
        assert dose["waste_cost_cents"] == 24000

    def test_the_charge_and_the_ledger_both_propagate(self, api):
        """The charge lands on the patient's running liability while the lot's wasted
        units rise and the chair and nurse release the visit's load.

        Design: Difficulty/combinatorial_formula/cancellation_charge_share_tier_keyed_on_provisional_total_mode_c
        """
        suite, lot, _appointment, _prep, _cancelled = self._late_cancellation(api)

        patient = read_patient(api, suite.patient_id)
        assert patient["waste_liability_cents"] == 10900
        assert patient["steering_status"] == SteeringStatus.SUITE
        assert patient["no_show_risk_score"] == pytest.approx(50.00, abs=0.005)
        assert patient["reminder_tier"] == ReminderTier.INTENSIVE

        row = read_lot(api, lot["id"])
        assert row["units_wasted"] == 2
        assert row["units_committed"] == 0
        assert row["units_available"] == 8
        assert row["status"] == LotStatus.AVAILABLE

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 0
