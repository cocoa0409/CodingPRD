"""Calls that violate two or three rules at once, where only the highest-priority
refusal may surface."""

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    LabResultStatus,
    PHARMACIST,
    PlanStatus,
    ReadinessStatus,
    ReminderTier,
    SCHEDULER,
    ScheduleStatus,
    SteeringStatus,
    check_in_visit,
    confirm_visit,
    file_lab_result,
    inject_history,
    make_appointment_payload,
    make_nurse_headers,
    read_appointment,
    read_chair,
    read_lab_result,
    read_nurse,
    read_patient,
    read_plan,
    set_clock,
    setup_approved_authorization,
    setup_booked_visit,
    setup_suite,
    validate_error,
    validate_paginated,
)


class TestLabGateOutranksTheMissingDose:
    """A start-infusion call that violates the clinical gate and the dose check."""

    def _checked_in_with_a_failing_draw(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock="2026-08-05T07:00:00Z",
            service_date="2026-08-10",
            requested_start_minute=540,
            drug_kind="gate",
        )
        setup_approved_authorization(api, appointment["id"])
        confirm_visit(api, appointment["id"])
        set_clock(api, "2026-08-10T08:00:00Z")
        lab = file_lab_result(
            api,
            suite.patient_id,
            collected_at="2026-08-10T07:00:00Z",
            anc_value=1.2,
            platelet_value=150,
            headers=make_nurse_headers(suite.nurse_id),
        )
        check_in_visit(api, appointment["id"])
        return suite, appointment, lab

    def test_the_clinical_gate_answers_before_the_dose_lookup(self, api):
        """The draw's count is below the drug's minimum and no dose was ever compounded;
        the clinical safety refusal is the one the nurse must see.

        Design: Difficulty/priority_pair_validation_conflict/lab_gate_priority_73_beats_preparation_not_ready_priority_100_on_start_infusion
        """
        suite, appointment, _lab = self._checked_in_with_a_failing_draw(api)

        response = api.start_infusion(
            appointment["id"], make_nurse_headers(suite.nurse_id)
        )

        body = validate_error(response, ApiErrorId.ERR_LAB_GATE_NOT_MET, 422)
        assert body["error_id"] != ApiErrorId.ERR_PREPARATION_NOT_READY

    def test_no_dose_was_ever_standing_by_for_this_visit(self, api):
        """The cheaper downstream-readiness lookup was equally violated: the visit has no
        compounded dose at all.

        Design: Difficulty/priority_pair_validation_conflict/lab_gate_priority_73_beats_preparation_not_ready_priority_100_on_start_infusion
        """
        suite, appointment, _lab = self._checked_in_with_a_failing_draw(api)
        api.start_infusion(appointment["id"], make_nurse_headers(suite.nurse_id))

        rows, _meta = validate_paginated(
            api.list_drug_preparations(PHARMACIST, {"appointment_id": appointment["id"]})
        )
        assert rows == []

    def test_the_refusal_leaves_the_visit_seated_and_the_draw_stored(self, api):
        """The schedule dimension does not move, the readiness dimension shows the
        laboratory leg never cleared, and the failing value is still on file.

        Design: Difficulty/priority_pair_validation_conflict/lab_gate_priority_73_beats_preparation_not_ready_priority_100_on_start_infusion
        """
        suite, appointment, lab = self._checked_in_with_a_failing_draw(api)
        api.start_infusion(appointment["id"], make_nurse_headers(suite.nurse_id))

        row = read_appointment(api, appointment["id"])
        assert row["schedule_status"] == ScheduleStatus.CHECKED_IN
        assert row["actual_start_minute"] is None
        assert row["readiness_status"] == ReadinessStatus.AUTH_CLEARED

        draw = read_lab_result(api, lab["id"])
        assert draw["status"] == LabResultStatus.RESULTED
        assert draw["anc_value"] == pytest.approx(1.2, abs=0.005)


class TestSuspendedPlanOutranksTheOperatingHoursWindow:
    """A booking that breaks the regimen state, the steering hold and the day boundary."""

    def _suspended_by_three_no_shows(self, api: ApiClient):
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
        injected = []
        for cycle, service_date in enumerate(
            ("2026-07-08", "2026-07-22", "2026-08-03"), start=1
        ):
            injected.append(
                inject_history(
                    api,
                    suite.center_id,
                    suite.patient_id,
                    suite.plan_id,
                    suite.template_id,
                    service_date=service_date,
                    schedule_status=ScheduleStatus.NO_SHOW,
                    chair_minutes=240,
                    start_minute=540,
                    cycle_number=cycle,
                )
            )
        return suite, injected

    def _attempt_late_booking(self, api: ApiClient, suite):
        return api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-12",
                requested_start_minute=1080,
                cycle_number=4,
            ),
            SCHEDULER,
        )

    def test_the_regimen_state_is_the_refusal_that_surfaces(self, api):
        """Three rules are broken by the same booking; the state precondition on the
        regimen outranks both the steering hold and the operating-hours window.

        Design: Difficulty/priority_pair_validation_conflict/plan_suspended_priority_45_beats_outside_operating_hours_priority_94_on_booking
        """
        suite, _injected = self._suspended_by_three_no_shows(api)

        response = self._attempt_late_booking(api, suite)

        body = validate_error(response, ApiErrorId.ERR_PLAN_SUSPENDED, 409)
        assert body["error_id"] != ApiErrorId.ERR_OUTSIDE_OPERATING_HOURS
        assert body["error_id"] != ApiErrorId.ERR_PATIENT_STEERING_HOLD

    def test_the_third_strike_flipped_steering_and_suspended_the_regimen(self, api):
        """A third strike inside the trailing window moves the patient to
        HOME_INFUSION_REVIEW, and that flip suspends every active regimen.

        Design: Difficulty/priority_pair_validation_conflict/plan_suspended_priority_45_beats_outside_operating_hours_priority_94_on_booking
        """
        suite, _injected = self._suspended_by_three_no_shows(api)

        patient = read_patient(api, suite.patient_id)
        assert patient["no_show_strikes"] == 3
        assert patient["steering_status"] == SteeringStatus.HOME_INFUSION_REVIEW
        assert patient["no_show_risk_score"] == pytest.approx(100.00, abs=0.005)
        assert patient["reminder_tier"] == ReminderTier.INTENSIVE

        assert read_plan(api, suite.plan_id)["status"] == PlanStatus.SUSPENDED

    def test_the_refused_booking_reserved_nothing(self, api):
        """A refused booking writes no visit and consumes neither chair minutes nor
        nurse acuity, and injected history never held either in the first place.

        Design: Difficulty/priority_pair_validation_conflict/plan_suspended_priority_45_beats_outside_operating_hours_priority_94_on_booking
        """
        suite, injected = self._suspended_by_three_no_shows(api)

        self._attempt_late_booking(api, suite)

        rows, _meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": suite.patient_id})
        )
        assert len(rows) == len(injected)
        assert {row["schedule_status"] for row in rows} == {ScheduleStatus.NO_SHOW}

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 0
