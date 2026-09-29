"""Single calls whose consequences run several links deep and cross into rows the
caller never named."""

from test_helpers import (
    AdverseEventStatus,
    ApiClient,
    LotStatus,
    PlanStatus,
    PreparationStatus,
    ReadinessStatus,
    ScheduleStatus,
    SteeringStatus,
    add_patient_with_plan,
    book_appointment,
    check_in_visit,
    compound_dose,
    confirm_visit,
    create_lot,
    file_lab_result,
    make_nurse_headers,
    read_appointment,
    read_adverse_event,
    read_chair,
    read_lot,
    read_nurse,
    read_patient,
    read_plan,
    read_preparation,
    record_reaction,
    request_dose,
    set_clock,
    setup_approved_authorization,
    setup_suite,
    start_infusion,
    validate_success,
    SCHEDULER,
)


class TestCancellationCascadesThroughLiabilityIntoTheSiblingVisit:
    """One cancel call: waste, charge, steering flip, plan suspension, sibling cancel."""

    def _cancelled_first_cycle(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-05T07:00:00Z",
            drug_kind="gate",
            drug_overrides={
                "requires_lab_gate": False,
                "lab_min_anc": None,
                "lab_min_platelets": None,
            },
        )
        lot = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-A",
            units_received=10,
            expires_on="2026-12-01T00:00:00Z",
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
        second = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-17",
            requested_start_minute=540,
            cycle_number=2,
        )
        prep = request_dose(api, first["id"], 4)
        set_clock(api, "2026-08-10T08:30:00Z")
        prep = compound_dose(api, prep["id"])
        cancelled = validate_success(
            api.cancel_appointment(
                first["id"], SCHEDULER, {"reason": "Acute infection, treatment deferred"}
            ),
            200,
        )
        return suite, lot, cancelled, second, prep

    def test_the_cancelled_visit_wastes_its_dose_and_rewrites_the_lot_ledger(self, api):
        """Cancelling a visit with a compounded dose standing by wastes that dose and
        recomputes the backing lot's counters.

        Design: Difficulty/transitive_cascade/cancel_wastes_dose_then_steers_patient_then_suspends_plan_then_cancels_sibling
        """
        _suite, lot, cancelled, _second, prep = self._cancelled_first_cycle(api)

        assert cancelled["schedule_status"] == ScheduleStatus.CANCELLED
        assert cancelled["late_cancellation"] is True

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.WASTED
        assert dose["waste_cost_cents"] == 360000

        row = read_lot(api, lot["id"])
        assert row["units_committed"] == 0
        assert row["units_wasted"] == 4
        assert row["units_returned"] == 0
        assert row["units_available"] == 6
        assert row["status"] == LotStatus.AVAILABLE

    def test_the_waste_prices_a_charge_that_lands_on_the_running_liability(self, api):
        """The wasted dose feeds the provisional total, the share tier prices it, and the
        resulting charge accumulates on the patient's running liability.

        Design: Difficulty/transitive_cascade/cancel_wastes_dose_then_steers_patient_then_suspends_plan_then_cancels_sibling
        """
        suite, _lot, cancelled, _second, _prep = self._cancelled_first_cycle(api)

        assert cancelled["cancellation_charge_cents"] == 128500

        patient = read_patient(api, suite.patient_id)
        assert patient["waste_liability_cents"] == 128500

    def test_crossing_the_liability_threshold_flips_steering_and_suspends_the_regimen(
        self, api
    ):
        """A liability at or above the steering threshold moves the patient to
        HOME_INFUSION_REVIEW, and that flip suspends the patient's active regimen.

        Design: Difficulty/transitive_cascade/cancel_wastes_dose_then_steers_patient_then_suspends_plan_then_cancels_sibling
        """
        suite, _lot, _cancelled, _second, _prep = self._cancelled_first_cycle(api)

        patient = read_patient(api, suite.patient_id)
        assert patient["steering_status"] == SteeringStatus.HOME_INFUSION_REVIEW
        assert patient["no_show_strikes"] == 0

        assert read_plan(api, suite.plan_id)["status"] == PlanStatus.SUSPENDED

    def test_the_suspension_zero_charge_cancels_the_untouched_sibling_visit(self, api):
        """Suspending the regimen cancels its still-live visits at zero charge and
        releases the chair minutes and nurse acuity they were holding.

        Design: Difficulty/transitive_cascade/cancel_wastes_dose_then_steers_patient_then_suspends_plan_then_cancels_sibling
        """
        suite, _lot, _cancelled, second, _prep = self._cancelled_first_cycle(api)

        sibling = read_appointment(api, second["id"])
        assert sibling["schedule_status"] == ScheduleStatus.CANCELLED
        assert sibling["cancellation_charge_cents"] == 0
        assert sibling["late_cancellation"] is False

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 0

        assert read_patient(api, suite.patient_id)["waste_liability_cents"] == 128500


class TestReactionExtensionBumpsAnUnrelatedVisit:
    """A clinical event on one patient un-seats a different patient's confirmed visit."""

    def _reaction_on_the_morning_visit(self, api: ApiClient):
        suite = setup_suite(api, clock="2026-08-05T07:00:00Z", drug_kind="gate")
        create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-A",
            units_received=10,
            expires_on="2026-12-01T00:00:00Z",
        )
        morning = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=540,
            cycle_number=1,
        )
        patient2, plan2 = add_patient_with_plan(api, suite, "MRN-0002", "Pat Two")
        afternoon = book_appointment(
            api,
            suite.center_id,
            patient2["id"],
            plan2["id"],
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=795,
            cycle_number=1,
        )
        for visit_id in (morning["id"], afternoon["id"]):
            setup_approved_authorization(api, visit_id)
        confirm_visit(api, morning["id"])
        afternoon = confirm_visit(api, afternoon["id"])

        set_clock(api, "2026-08-10T08:00:00Z")
        file_lab_result(
            api,
            suite.patient_id,
            collected_at="2026-08-10T07:00:00Z",
            anc_value=2.0,
            platelet_value=150,
            headers=make_nurse_headers(suite.nurse_id),
        )
        prep = request_dose(api, morning["id"], 2)
        prep = compound_dose(api, prep["id"])
        check_in_visit(api, morning["id"])
        start_infusion(api, morning["id"], suite.nurse_id)
        return suite, morning, afternoon, prep

    def test_a_grade_three_reaction_extends_the_observation_and_chair_legs(self, api):
        """The extension is looked up from the grade and added to both the observation
        leg and the chair window, moving the end minute without moving the start.

        Design: Difficulty/transitive_cascade/adverse_event_extension_bumps_later_appointment_off_the_shared_chair
        """
        suite, morning, _afternoon, _prep = self._reaction_on_the_morning_visit(api)

        event = record_reaction(
            api,
            morning["id"],
            suite.nurse_id,
            grade=3,
            action="HOLD",
            note="Rigors and hypotension 20 minutes into the infusion",
        )

        assert event["observation_extension_minutes"] == 60

        row = read_appointment(api, morning["id"])
        assert row["observation_minutes"] == 120
        assert row["chair_minutes"] == 300
        assert row["start_minute"] == 540
        assert row["end_minute"] == 840

    def test_the_reacting_visit_is_blocked_yet_still_infusing(self, api):
        """The record is filed against the nurse who reported it, the readiness dimension
        goes to BLOCKED, and the schedule dimension does not move at all.

        Design: Difficulty/transitive_cascade/adverse_event_extension_bumps_later_appointment_off_the_shared_chair
        """
        suite, morning, _afternoon, _prep = self._reaction_on_the_morning_visit(api)

        event = record_reaction(
            api,
            morning["id"],
            suite.nurse_id,
            grade=3,
            action="HOLD",
            note="Rigors and hypotension 20 minutes into the infusion",
        )

        stored = read_adverse_event(api, event["id"])
        assert stored["status"] == AdverseEventStatus.REPORTED
        assert stored["reported_by_nurse_id"] == suite.nurse_id

        row = read_appointment(api, morning["id"])
        assert row["readiness_status"] == ReadinessStatus.BLOCKED
        assert row["schedule_status"] == ScheduleStatus.INFUSING
        assert row["actual_start_minute"] == 480

    def test_the_extension_bumps_the_later_visit_off_the_shared_chair(self, api):
        """The lengthened occupancy is re-evaluated against later visits on the same chair
        and day, so the colliding visit is demoted with its chair and nurse cleared.

        Design: Difficulty/transitive_cascade/adverse_event_extension_bumps_later_appointment_off_the_shared_chair
        """
        suite, morning, afternoon, _prep = self._reaction_on_the_morning_visit(api)
        assert afternoon["schedule_status"] == ScheduleStatus.CONFIRMED

        record_reaction(
            api,
            morning["id"],
            suite.nurse_id,
            grade=3,
            action="HOLD",
            note="Rigors and hypotension 20 minutes into the infusion",
        )

        bumped = read_appointment(api, afternoon["id"])
        assert bumped["schedule_status"] == ScheduleStatus.TENTATIVE
        assert bumped["chair_id"] is None
        assert bumped["nurse_id"] is None
        assert bumped["start_minute"] == 795
        assert bumped["chair_minutes"] == 240

    def test_only_the_extended_visit_still_holds_the_chair_and_the_nurse(self, api):
        """The bump recomputes the derived load figures, and a reported reaction on its
        own never touches the regimen.

        Design: Difficulty/transitive_cascade/adverse_event_extension_bumps_later_appointment_off_the_shared_chair
        """
        suite, morning, _afternoon, _prep = self._reaction_on_the_morning_visit(api)

        record_reaction(
            api,
            morning["id"],
            suite.nurse_id,
            grade=3,
            action="HOLD",
            note="Rigors and hypotension 20 minutes into the infusion",
        )

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 300
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3
        assert read_plan(api, suite.plan_id)["status"] == PlanStatus.ACTIVE
