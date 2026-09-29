"""Reversals that must restore the derived ledgers exactly, and the one ledger that is
deliberately never restored."""

import pytest

from test_helpers import (
    ApiClient,
    DoseTier,
    LotStatus,
    PHARMACIST,
    PreparationStatus,
    ReminderTier,
    SCHEDULER,
    ScheduleStatus,
    SteeringStatus,
    assert_lot_ledger_conserved,
    book_appointment,
    create_lot,
    create_patient,
    create_plan,
    create_template,
    create_ungated_drug,
    make_return_payload,
    read_appointment,
    read_chair,
    read_lot,
    read_nurse,
    read_patient,
    read_preparation,
    request_dose,
    setup_suite,
    validate_success,
)


class TestReturningAnUncompoundedDoseRestoresTheLotIdentity:
    """units_returned records the movement but stays outside the balance."""

    def _whole_lot_committed(self, api: ApiClient):
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
        )
        prep = request_dose(api, appointment["id"], 10)
        return suite, lot, appointment, prep

    def _return_the_dose(self, api: ApiClient, prep_id: str):
        return validate_success(
            api.return_dose(
                prep_id,
                PHARMACIST,
                make_return_payload(
                    "Visit moved to the home-infusion pathway; dose never compounded"
                ),
            ),
            200,
        )

    def test_committing_every_unit_of_the_lot_depletes_it(self, api):
        """Requesting the lot's entire holding drives units_available to zero and takes the
        lot out of the candidate pool, with the unit identity still balanced.

        Design: Difficulty/compensating_invariant/lot_unit_ledger_fully_restored_by_returning_an_uncompounded_dose
        """
        _suite, lot, _appointment, _prep = self._whole_lot_committed(api)

        row = read_lot(api, lot["id"])
        assert row["units_received"] == 10
        assert row["units_committed"] == 10
        assert row["units_available"] == 0
        assert row["units_administered"] == 0
        assert row["units_wasted"] == 0
        assert row["units_returned"] == 0
        assert row["status"] == LotStatus.DEPLETED
        assert_lot_ledger_conserved(row)

    def test_the_return_restores_the_balance_and_re_enters_the_pool(self, api):
        """The committed units are released and the audit counter records the return, but
        that counter is not one of the terms of the balance.

        Design: Difficulty/compensating_invariant/lot_unit_ledger_fully_restored_by_returning_an_uncompounded_dose
        """
        _suite, lot, _appointment, prep = self._whole_lot_committed(api)

        self._return_the_dose(api, prep["id"])

        row = read_lot(api, lot["id"])
        assert row["units_committed"] == 0
        assert row["units_available"] == 10
        assert row["units_returned"] == 10
        assert row["units_received"] == 10
        assert row["units_administered"] == 0
        assert row["units_wasted"] == 0
        assert row["status"] == LotStatus.AVAILABLE
        assert_lot_ledger_conserved(row)

    def test_a_return_is_not_a_cancellation(self, api):
        """Returning an uncompounded dose costs nothing and leaves the visit itself where
        it stood.

        Design: Difficulty/compensating_invariant/lot_unit_ledger_fully_restored_by_returning_an_uncompounded_dose
        """
        suite, _lot, appointment, prep = self._whole_lot_committed(api)

        self._return_the_dose(api, prep["id"])

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.RETURNED
        assert dose["waste_cost_cents"] == 0

        visit = read_appointment(api, appointment["id"])
        assert visit["schedule_status"] == ScheduleStatus.TENTATIVE
        assert visit["cancellation_charge_cents"] == 0

        assert read_patient(api, suite.patient_id)["waste_liability_cents"] == 0


class TestEarlyCancellationRestoresChairAndAcuityButNotAdherence:
    """The resource ledgers unwind completely; the adherence history does not."""

    def _two_visits_sharing_one_chair(self, api: ApiClient):
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
        short_drug = create_ungated_drug(api)
        short_template = create_template(
            api, suite.center_id, short_drug["id"], DoseTier.LOW
        )
        patient2 = create_patient(api, "MRN-0002", "Pat Two")
        plan2 = create_plan(
            api,
            patient2["id"],
            short_drug["id"],
            dose_mg_per_kg=5,
            total_cycles=4,
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
            patient2["id"],
            plan2["id"],
            short_template["id"],
            service_date="2026-08-10",
            requested_start_minute=795,
            cycle_number=1,
        )
        return suite, patient2, first, second

    def _cancel_second(self, api: ApiClient, appointment_id: str):
        return validate_success(
            api.cancel_appointment(
                appointment_id, SCHEDULER, {"reason": "Patient travelling that week"}
            ),
            200,
        )

    def test_the_second_booking_stacks_onto_the_shared_ledgers(self, api):
        """Both visits sit on the same chair and the same nurse, so the derived figures
        carry the sum before anything is cancelled.

        Design: Difficulty/compensating_invariant/chair_committed_minutes_and_nurse_acuity_fully_restored_by_an_early_cancellation
        """
        suite, _patient2, _first, second = self._two_visits_sharing_one_chair(api)

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 330
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 5

        assert second["chair_id"] == suite.chair_id("A1")
        assert second["start_minute"] == 795
        assert second["end_minute"] == 885

    def test_cancelling_returns_the_ledgers_to_their_earlier_values_exactly(self, api):
        """The release subtracts exactly the cancelled visit's own contribution, leaving
        the first visit's figures and the first visit itself untouched.

        Design: Difficulty/compensating_invariant/chair_committed_minutes_and_nurse_acuity_fully_restored_by_an_early_cancellation
        """
        suite, _patient2, first, second = self._two_visits_sharing_one_chair(api)

        self._cancel_second(api, second["id"])

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3

        survivor = read_appointment(api, first["id"])
        assert survivor["schedule_status"] == ScheduleStatus.TENTATIVE
        assert survivor["chair_id"] == suite.chair_id("A1")
        assert survivor["start_minute"] == 540
        assert survivor["end_minute"] == 780

    def test_a_cancellation_well_outside_the_late_window_is_free(self, api):
        """Far enough ahead of the visit and with no compounded dose, the cancellation
        carries no charge at all.

        Design: Difficulty/compensating_invariant/chair_committed_minutes_and_nurse_acuity_fully_restored_by_an_early_cancellation
        """
        _suite, patient2, _first, second = self._two_visits_sharing_one_chair(api)

        cancelled = self._cancel_second(api, second["id"])

        assert cancelled["schedule_status"] == ScheduleStatus.CANCELLED
        assert cancelled["late_cancellation"] is False
        assert cancelled["cancellation_charge_cents"] == 0

        assert read_patient(api, patient2["id"])["waste_liability_cents"] == 0

    def test_the_adherence_ledger_is_deliberately_not_compensated(self, api):
        """The cancellation is permanently part of the patient's own history and moves the
        risk figure and the reminder tier, while the other patient is untouched.

        Design: Difficulty/compensating_invariant/chair_committed_minutes_and_nurse_acuity_fully_restored_by_an_early_cancellation
        """
        suite, patient2, _first, second = self._two_visits_sharing_one_chair(api)

        self._cancel_second(api, second["id"])

        cancelling_patient = read_patient(api, patient2["id"])
        assert cancelling_patient["no_show_risk_score"] == pytest.approx(25.00, abs=0.005)
        assert cancelling_patient["reminder_tier"] == ReminderTier.ELEVATED
        assert cancelling_patient["no_show_strikes"] == 0
        assert cancelling_patient["steering_status"] == SteeringStatus.SUITE

        other = read_patient(api, suite.patient_id)
        assert other["no_show_risk_score"] == pytest.approx(0.00, abs=0.005)
        assert other["reminder_tier"] == ReminderTier.STANDARD
