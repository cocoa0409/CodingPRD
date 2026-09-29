"""Every machine's birth state, its legal edges, the states that refuse an edge outright,
and the side effects a single accepted edge fans out across the estate."""

import pytest

from test_helpers import (
    AUTH_SPECIALIST,
    MEDICAL_DIRECTOR,
    PHARMACIST,
    SCHEDULER,
    AdverseEventStatus,
    ApiClient,
    ApiErrorId,
    AuthStatus,
    LotStatus,
    NurseStatus,
    PlanStatus,
    PreparationStatus,
    ReadinessStatus,
    ReminderTier,
    ReviewOutcome,
    ScheduleStatus,
    assert_assigned_acuity,
    assert_committed_minutes,
    assert_day_billing,
    assert_instant_equals,
    assert_lot_ledger_conserved,
    assert_sweep_counters,
    book_appointment,
    check_in_visit,
    close_review,
    complete_infusion,
    compound_dose,
    confirm_visit,
    create_lot,
    discharge_visit,
    file_authorization,
    file_lab_result,
    make_approval_decision_payload,
    make_cancel_payload,
    make_nurse_headers,
    make_reschedule_payload,
    make_resume_payload,
    make_return_payload,
    open_review,
    read_appointment,
    read_authorization,
    read_chair,
    read_chair_billing,
    read_lot,
    read_nurse,
    read_patient,
    read_plan,
    read_preparation,
    record_reaction,
    request_dose,
    run_sweep,
    set_clock,
    setup_approved_authorization,
    setup_booked_visit,
    setup_confirmed_visit,
    setup_suite,
    start_infusion,
    submit_authorization,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The booking is filed five days out, the visit runs on the tenth.
SETUP_CLOCK = "2026-08-05T07:00:00Z"
SERVICE_DATE = "2026-08-10"
START_MINUTE = 540

#: The four instants the visit day is walked through.
COMPOUNDING_CLOCK = "2026-08-10T08:30:00Z"
START_CLOCK = "2026-08-10T09:00:00Z"
COMPLETION_CLOCK = "2026-08-10T11:30:00Z"
DISCHARGE_CLOCK = "2026-08-10T13:15:00Z"

#: Drawn on the morning of the visit, two and a half hours before the mix.
LAB_COLLECTED_AT = "2026-08-10T07:00:00Z"


def _chain_to_observing(
    api: ApiClient,
    total_cycles: int = 6,
    chair_labels: tuple = ("A1",),
    nurse_specs: list = None,
    lot_units: int = 10,
):
    """Walk one visit all the way from a booking to OBSERVING on its own service day.

    Every hop is taken through its own endpoint at its own instant, so the visit ends up
    with ``actual_start_minute`` 540 and the logical clock sitting at 11:30 UTC. Returns
    ``(suite, appointment, preparation)``.
    """
    suite, appointment = setup_booked_visit(
        api,
        clock=SETUP_CLOCK,
        service_date=SERVICE_DATE,
        requested_start_minute=START_MINUTE,
        chair_labels=chair_labels,
        nurse_specs=nurse_specs,
        plan_overrides={"total_cycles": total_cycles},
    )
    create_lot(api, suite.drug_id, units_received=lot_units)
    setup_approved_authorization(api, appointment["id"], approved_units=1)
    confirm_visit(api, appointment["id"])

    set_clock(api, COMPOUNDING_CLOCK)
    file_lab_result(
        api,
        suite.patient_id,
        collected_at=LAB_COLLECTED_AT,
        anc_value=2.0,
        platelet_value=150,
    )
    prep = request_dose(api, appointment["id"], 1)
    prep = compound_dose(api, prep["id"])
    check_in_visit(api, appointment["id"])

    set_clock(api, START_CLOCK)
    start_infusion(api, appointment["id"], suite.nurse_id)

    set_clock(api, COMPLETION_CLOCK)
    observing = complete_infusion(api, appointment["id"], suite.nurse_id)
    return suite, observing, prep


def _chain_to_completed(api: ApiClient, **kwargs):
    """The same walk, discharged at 13:15 so the realised occupancy is 255 minutes."""
    suite, observing, prep = _chain_to_observing(api, **kwargs)
    set_clock(api, DISCHARGE_CLOCK)
    completed = discharge_visit(api, observing["id"], suite.nurse_id)
    return suite, completed, prep


class TestSubmissionIsTheFirstEdgeOutOfDraft:
    """The submission edge moves one row, counts itself, and leaves the visit alone."""

    def _drafted_coverage(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock=SETUP_CLOCK,
            service_date=SERVICE_DATE,
            requested_start_minute=START_MINUTE,
        )
        auth = file_authorization(api, appointment["id"])
        return suite, appointment, auth

    def test_the_request_leaves_draft_for_submitted_with_its_counter_at_one(self, api):
        """A DRAFT request submits to SUBMITTED, its submission_count rises by one and its
        version advances, while every decision field stays empty because no payer has
        answered yet.

        Design: Corner/state_machines/authorization_submit_moves_draft_to_submitted_and_counts_the_submission
        """
        _suite, _appointment, auth = self._drafted_coverage(api)
        assert auth["status"] == AuthStatus.DRAFT
        assert auth["submission_count"] == 0
        assert auth["version"] == 1

        submitted = submit_authorization(api, auth["id"])

        assert submitted["status"] == AuthStatus.SUBMITTED
        assert submitted["submission_count"] == 1
        assert submitted["decided_at"] is None
        assert submitted["expires_at"] is None
        assert submitted["approved_units"] is None
        assert submitted["version"] == 2

    def test_the_visit_the_request_covers_is_not_moved_by_the_submission(self, api):
        """Submitting only re-derives the visit's readiness, and with the coverage merely
        SUBMITTED neither the payer nor the laboratory condition holds, so the visit stays
        in TENTATIVE at PENDING on its original version.

        Design: Corner/state_machines/authorization_submit_moves_draft_to_submitted_and_counts_the_submission
        """
        _suite, appointment, auth = self._drafted_coverage(api)

        submit_authorization(api, auth["id"])

        visit = read_appointment(api, appointment["id"])
        assert visit["schedule_status"] == ScheduleStatus.TENTATIVE
        assert visit["readiness_status"] == ReadinessStatus.PENDING
        assert visit["version"] == 1


class TestEveryMachineIsBornWhereItsModelSays:
    """Five machines, five creation endpoints, five declared initial states."""

    def _fresh_estate(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock=SETUP_CLOCK,
            service_date=SERVICE_DATE,
            requested_start_minute=START_MINUTE,
        )
        lot = create_lot(api, suite.drug_id, units_received=10)
        auth = file_authorization(api, appointment["id"])
        prep = request_dose(api, appointment["id"], 1)
        return suite, appointment, lot, auth, prep

    def test_a_regimen_starts_active_with_no_cycle_behind_it(self, api):
        """A regimen is ACTIVE from creation with completed_cycles at zero, and because that
        counter has not reached one its first_dose_completed flag reads false.

        Design: Corner/state_machines/every_machine_is_born_in_its_declared_initial_state
        """
        suite, _appointment, _lot, _auth, _prep = self._fresh_estate(api)

        plan = read_plan(api, suite.plan_id)
        assert plan["status"] == PlanStatus.ACTIVE
        assert plan["completed_cycles"] == 0
        assert plan["first_dose_completed"] is False

    def test_a_visit_is_born_tentative_on_a_schedule_and_pending_on_readiness(self, api):
        """The two dimensions start independently: a fresh booking is TENTATIVE on the
        schedule while neither the payer nor the laboratory condition holds, so readiness
        reads PENDING.

        Design: Corner/state_machines/every_machine_is_born_in_its_declared_initial_state
        """
        _suite, appointment, _lot, _auth, _prep = self._fresh_estate(api)

        visit = read_appointment(api, appointment["id"])
        assert visit["schedule_status"] == ScheduleStatus.TENTATIVE
        assert visit["readiness_status"] == ReadinessStatus.PENDING

    def test_coverage_starts_in_draft_and_a_dose_starts_unmixed(self, api):
        """A filed request is DRAFT with submission_count at zero, and a requested dose is
        REQUESTED with neither of the two compounding stamps written.

        Design: Corner/state_machines/every_machine_is_born_in_its_declared_initial_state
        """
        _suite, _appointment, _lot, auth, prep = self._fresh_estate(api)

        coverage = read_authorization(api, auth["id"])
        assert coverage["status"] == AuthStatus.DRAFT
        assert coverage["submission_count"] == 0

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.REQUESTED
        assert dose["prepared_at"] is None
        assert dose["usable_until"] is None

    def test_a_lot_starts_available_and_only_the_commitment_moves_its_counters(self, api):
        """Ten units arrive with every counter but units_available at zero; the single
        one-unit commitment then moves units_committed and units_available alone.

        Design: Corner/state_machines/every_machine_is_born_in_its_declared_initial_state
        """
        _suite, _appointment, lot, _auth, _prep = self._fresh_estate(api)
        assert lot["status"] == LotStatus.AVAILABLE
        assert lot["units_available"] == 10

        row = read_lot(api, lot["id"])
        assert row["status"] == LotStatus.AVAILABLE
        assert row["units_received"] == 10
        assert row["units_committed"] == 1
        assert row["units_administered"] == 0
        assert row["units_wasted"] == 0
        assert row["units_returned"] == 0
        assert row["units_available"] == 9
        assert_lot_ledger_conserved(row)


class TestASettledVisitAcceptsNoFurtherEdge:
    """COMPLETED is a sink: three different edges into it are all refused the same way."""

    def test_cancel_check_in_and_reschedule_are_all_refused_as_terminal(self, api):
        """The terminal bar sits above every other precondition, so a cancellation, a
        check-in and a properly versioned reschedule against a discharged visit all report
        the same refusal rather than a state or window complaint.

        Design: Corner/state_machines/a_discharged_appointment_refuses_cancel_check_in_and_reschedule
        """
        _suite, completed, _prep = _chain_to_completed(api)
        assert completed["schedule_status"] == ScheduleStatus.COMPLETED

        validate_error(
            api.cancel_appointment(
                completed["id"], SCHEDULER, make_cancel_payload("No longer needed")
            ),
            ApiErrorId.ERR_APPOINTMENT_TERMINAL,
            409,
        )
        validate_error(
            api.check_in_appointment(completed["id"], SCHEDULER),
            ApiErrorId.ERR_APPOINTMENT_TERMINAL,
            409,
        )
        validate_error(
            api.reschedule_appointment(
                completed["id"],
                make_reschedule_payload(
                    completed["version"],
                    service_date="2026-08-17",
                    requested_start_minute=600,
                ),
                SCHEDULER,
            ),
            ApiErrorId.ERR_APPOINTMENT_TERMINAL,
            409,
        )

    def test_the_settled_figures_survive_all_three_refusals_untouched(self, api):
        """Nothing about the settlement is disturbed: the realised window, the quarter-hour
        billing, the zero cancellation charge and the version all read exactly as they did
        at discharge.

        Design: Corner/state_machines/a_discharged_appointment_refuses_cancel_check_in_and_reschedule
        """
        _suite, completed, _prep = _chain_to_completed(api)
        version_at_discharge = completed["version"]

        api.cancel_appointment(
            completed["id"], SCHEDULER, make_cancel_payload("No longer needed")
        )
        api.check_in_appointment(completed["id"], SCHEDULER)
        api.reschedule_appointment(
            completed["id"],
            make_reschedule_payload(version_at_discharge, service_date="2026-08-17"),
            SCHEDULER,
        )

        row = read_appointment(api, completed["id"])
        assert row["schedule_status"] == ScheduleStatus.COMPLETED
        assert row["cancellation_charge_cents"] == 0
        assert row["late_cancellation"] is False
        assert row["actual_start_minute"] == 540
        assert row["actual_end_minute"] == 795
        assert row["billable_chair_units"] == 17
        assert row["version"] == version_at_discharge

    def test_the_refused_reschedule_minted_no_replacement_row(self, api):
        """A reschedule that gets through mints a successor carrying
        rescheduled_from_appointment_id; a refused one leaves that filter empty.

        Design: Corner/state_machines/a_discharged_appointment_refuses_cancel_check_in_and_reschedule
        """
        _suite, completed, _prep = _chain_to_completed(api)

        api.reschedule_appointment(
            completed["id"],
            make_reschedule_payload(completed["version"], service_date="2026-08-17"),
            SCHEDULER,
        )

        successors, _meta = validate_paginated(
            api.list_appointments(
                SCHEDULER, {"rescheduled_from_appointment_id": completed["id"]}
            )
        )
        assert successors == []


class TestDischargeSettlesTheWholeEstate:
    """One discharge moves the dose, the lot, the chair, the nurse, the regimen and the
    patient, and lands in the day's billing figures."""

    def test_the_last_cycle_bubbles_the_regimen_out_of_active(self, api):
        """completed_cycles is recomputed at discharge, and on a one-cycle regimen that
        recomputation reaches total_cycles, so the regimen itself leaves ACTIVE.

        Design: Corner/state_machines/discharge_administers_the_dose_and_bubbles_plan_completion_upward
        """
        suite, completed, _prep = _chain_to_completed(api, total_cycles=1)
        assert completed["schedule_status"] == ScheduleStatus.COMPLETED

        plan = read_plan(api, suite.plan_id)
        assert plan["total_cycles"] == 1
        assert plan["completed_cycles"] == 1
        assert plan["first_dose_completed"] is True
        assert plan["status"] == PlanStatus.COMPLETED

        patient = read_patient(api, suite.patient_id)
        assert patient["completed_appointment_count"] == 1
        assert patient["no_show_risk_score"] == pytest.approx(0.00, abs=0.005)
        assert patient["reminder_tier"] == ReminderTier.STANDARD

    def test_the_mixed_dose_is_consumed_and_the_lot_ledger_follows(self, api):
        """The dose standing by in PREPARED becomes ADMINISTERED, which moves the unit out
        of committed and into administered while leaving units_available where the original
        commitment had already put it.

        Design: Corner/state_machines/discharge_administers_the_dose_and_bubbles_plan_completion_upward
        """
        _suite, _completed, prep = _chain_to_completed(api, total_cycles=1)

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.ADMINISTERED

        lot = read_lot(api, dose["drug_lot_id"])
        assert lot["units_committed"] == 0
        assert lot["units_administered"] == 1
        assert lot["units_wasted"] == 0
        assert lot["units_available"] == 9
        assert lot["status"] == LotStatus.AVAILABLE
        assert_lot_ledger_conserved(lot)

    def test_the_chair_and_the_nurse_are_released_and_the_day_is_billed(self, api):
        """COMPLETED sits outside the committed set, so the chair's minutes and the nurse's
        acuity fall back to zero, while the 255-minute realised occupancy bills seventeen
        quarter-hour units at ninety dollars each.

        Design: Corner/state_machines/discharge_administers_the_dose_and_bubbles_plan_completion_upward
        """
        suite, completed, _prep = _chain_to_completed(api, total_cycles=1)

        assert_committed_minutes(read_chair(api, suite.chair_id("A1")), 0)
        assert_assigned_acuity(read_nurse(api, suite.nurse_id), 0)

        assert completed["billable_chair_units"] == 17

        summary = read_chair_billing(api, suite.center_id, SERVICE_DATE)
        assert summary["completed_appointment_count"] == 1
        assert summary["day_billable_units"] == 17
        assert summary["day_billable_cents"] == 153000
        assert_day_billing(summary)


class TestAnEdgeAttemptedFromTheWrongStateNamesTheState:
    """Two machines, two wrong source states, two refusals that both point at the status
    of the row addressed rather than at anything downstream of it."""

    def _confirmed_visit_and_a_second_drafted_request(self, api: ApiClient):
        suite, appointment = setup_confirmed_visit(
            api,
            clock=SETUP_CLOCK,
            service_date=SERVICE_DATE,
            requested_start_minute=START_MINUTE,
        )
        second = file_authorization(api, appointment["id"], "Northbridge Mutual")
        return suite, appointment, second

    def test_starting_from_confirmed_reports_the_schedule_state_not_the_missing_dose(
        self, api
    ):
        """The infusion edge leaves CHECKED_IN only. The state precondition on the addressed
        visit sits above the clinical readiness checks, so a CONFIRMED visit with no dose
        standing by is refused on its status rather than for the absent dose.

        Design: Corner/state_machines/start_infusion_from_confirmed_and_decision_on_a_draft_are_both_invalid_states
        """
        suite, appointment, _second = self._confirmed_visit_and_a_second_drafted_request(api)

        response = api.start_infusion(
            appointment["id"], make_nurse_headers(suite.nurse_id)
        )

        body = validate_error(response, ApiErrorId.ERR_INVALID_SCHEDULE_STATE, 409)
        assert body["error_id"] != ApiErrorId.ERR_PREPARATION_NOT_READY

        row = read_appointment(api, appointment["id"])
        assert row["schedule_status"] == ScheduleStatus.CONFIRMED
        assert row["actual_start_minute"] is None

    def test_deciding_a_drafted_request_reports_the_authorization_state(self, api):
        """Recording a payer answer requires SUBMITTED, so a request still sitting in DRAFT
        is refused, and the refusal leaves it in DRAFT with nothing stamped.

        Design: Corner/state_machines/start_infusion_from_confirmed_and_decision_on_a_draft_are_both_invalid_states
        """
        _suite, _appointment, second = self._confirmed_visit_and_a_second_drafted_request(api)

        response = api.decide_authorization(
            second["id"], make_approval_decision_payload(1), AUTH_SPECIALIST
        )

        validate_error(response, ApiErrorId.ERR_INVALID_AUTH_STATE, 409)

        row = read_authorization(api, second["id"])
        assert row["status"] == AuthStatus.DRAFT
        assert row["decided_at"] is None
        assert row["version"] == 1

    def test_the_first_request_that_did_clear_the_visit_is_untouched(self, api):
        """The refusal on the second request is scoped to that row: the approval that
        actually confirmed the visit still reads APPROVED.

        Design: Corner/state_machines/start_infusion_from_confirmed_and_decision_on_a_draft_are_both_invalid_states
        """
        _suite, appointment, second = self._confirmed_visit_and_a_second_drafted_request(api)
        api.decide_authorization(
            second["id"], make_approval_decision_payload(1), AUTH_SPECIALIST
        )

        requests, _meta = validate_paginated(
            api.list_authorization_requests(
                SCHEDULER, {"appointment_id": appointment["id"], "status": AuthStatus.APPROVED}
            )
        )
        assert len(requests) == 1
        assert requests[0]["id"] != second["id"]


class TestTheCheckpointIsIdempotentAtAFixedClock:
    """Each step selects only rows still in its pre-transition status, so a second run at
    the same instant has nothing left to find."""

    def _expired_stock(self, api: ApiClient):
        suite = setup_suite(
            api, clock="2026-07-20T07:00:00Z", with_patient=True, with_plan=True
        )
        lot = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-JULY",
            units_received=10,
            expires_on="2026-07-31T00:00:00Z",
        )
        set_clock(api, "2026-08-02T07:00:00Z")
        return suite, lot

    def test_the_first_run_expires_the_lapsed_lot_and_counts_only_that(self, api):
        """The lot's expiry instant is behind the clock, so step one moves it out of
        AVAILABLE; nothing exists for the other three steps to move.

        Design: Corner/state_machines/a_second_daily_sweep_at_the_same_clock_reports_all_zero_counters
        """
        suite, lot = self._expired_stock(api)

        first = run_sweep(api, suite.center_id, "2026-08-02")

        assert_sweep_counters(first, 1, 0, 0, 0)
        assert read_lot(api, lot["id"])["status"] == LotStatus.EXPIRED

    def test_the_second_run_at_the_same_instant_reports_four_zeros(self, api):
        """Running the checkpoint again without advancing the clock is safe: the lot is no
        longer in a pre-transition status, so every counter comes back zero and the lot's
        own figures are exactly what the first run left.

        Design: Corner/state_machines/a_second_daily_sweep_at_the_same_clock_reports_all_zero_counters
        """
        suite, lot = self._expired_stock(api)
        run_sweep(api, suite.center_id, "2026-08-02")

        second = run_sweep(api, suite.center_id, "2026-08-02")

        assert_sweep_counters(second, 0, 0, 0, 0)

        row = read_lot(api, lot["id"])
        assert row["status"] == LotStatus.EXPIRED
        assert row["units_available"] == 10
        assert row["units_committed"] == 0
        assert row["units_wasted"] == 0


class TestTwoDosesLeaveRequestedByDifferentEdges:
    """REQUESTED forks: one dose is mixed, its sibling goes back to stock, and the ledger
    treats the two departures completely differently."""

    def _one_mixed_one_returned(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock=SETUP_CLOCK,
            service_date=SERVICE_DATE,
            requested_start_minute=START_MINUTE,
        )
        lot = create_lot(api, suite.drug_id, units_received=10)
        set_clock(api, COMPOUNDING_CLOCK)
        mixed = request_dose(api, appointment["id"], 1)
        stood_down = request_dose(api, appointment["id"], 1)
        mixed = compound_dose(api, mixed["id"])
        stood_down = validate_success(
            api.return_dose(
                stood_down["id"], PHARMACIST, make_return_payload("Second line not needed")
            ),
            200,
        )
        return suite, appointment, lot, mixed, stood_down

    def test_the_mix_stamps_both_instants_and_the_return_stamps_neither(self, api):
        """Compounding writes prepared_at from the clock and usable_until four hours later,
        the drug's whole stability window; a dose that never left REQUESTED carries neither
        stamp and no waste price, because nothing was ever mixed.

        Design: Corner/state_machines/two_preparations_leave_requested_by_two_different_edges_to_two_different_states
        """
        _suite, _appointment, _lot, mixed, stood_down = self._one_mixed_one_returned(api)

        assert mixed["status"] == PreparationStatus.PREPARED
        assert_instant_equals(mixed["prepared_at"], COMPOUNDING_CLOCK)
        assert_instant_equals(mixed["usable_until"], "2026-08-10T12:30:00Z")

        assert stood_down["status"] == PreparationStatus.RETURNED
        assert stood_down["prepared_at"] is None
        assert stood_down["usable_until"] is None
        assert stood_down["waste_cost_cents"] == 0

    def test_the_lot_keeps_one_unit_committed_and_books_the_other_back(self, api):
        """Mixing leaves the lot's counters completely alone, while the return is the
        compensating move: committed falls, returned rises, and units_available climbs back
        to where the second request had pushed it down from.

        Design: Corner/state_machines/two_preparations_leave_requested_by_two_different_edges_to_two_different_states
        """
        _suite, appointment, lot, mixed, stood_down = self._one_mixed_one_returned(api)

        row = read_lot(api, lot["id"])
        assert row["units_committed"] == 1
        assert row["units_returned"] == 1
        assert row["units_wasted"] == 0
        assert row["units_administered"] == 0
        assert row["units_available"] == 9
        assert row["status"] == LotStatus.AVAILABLE
        assert_lot_ledger_conserved(row)

        assert mixed["drug_lot_id"] == lot["id"]
        assert stood_down["drug_lot_id"] == lot["id"]
        assert mixed["appointment_id"] == appointment["id"]
        assert stood_down["appointment_id"] == appointment["id"]


class TestARosterEditDemotesTheVisitItStrands:
    """Moving a nurse out of service walks the same bump path a chair withdrawal does."""

    def _confirmed_visit_whose_nurse_goes_inactive(self, api: ApiClient):
        suite, appointment = setup_confirmed_visit(
            api,
            clock=SETUP_CLOCK,
            service_date=SERVICE_DATE,
            requested_start_minute=START_MINUTE,
            with_lab=False,
        )
        assert appointment["schedule_status"] == ScheduleStatus.CONFIRMED
        # PRD 3.6: the APPROVED decision's readiness movement is itself a mutation that
        # "advances the visit's version by one", and PRD 3.5 says confirmation advances it
        # again -- so booking, approval and confirmation put the visit at version 3.
        assert appointment["version"] == 3
        nurse = validate_success(
            api.update_nurse(suite.nurse_id, {"status": NurseStatus.INACTIVE}, SCHEDULER),
            200,
        )
        return suite, appointment, nurse

    def test_the_committed_visit_falls_back_to_tentative_with_both_seats_cleared(self, api):
        """Only ACTIVE nurses are selectable, so the edit cannot leave the visit standing on
        this one: it is demoted to TENTATIVE with chair_id and nurse_id both cleared, and the
        demotion is a further mutation on the visit after its booking and its confirmation.

        Design: Corner/state_machines/nurse_going_inactive_demotes_the_confirmed_visit_and_clears_both_assignments
        """
        _suite, appointment, nurse = self._confirmed_visit_whose_nurse_goes_inactive(api)

        assert nurse["status"] == NurseStatus.INACTIVE
        # Creation (1), the booking that "raises the chosen nurse's assigned_acuity_points"
        # -- a recomputation of a derived counter being itself a mutation that advances the
        # row's version -- (2), the status edit that "advances the nurse's version by one"
        # (3), and the demotion's recompute of the released acuity back to zero (4).
        assert nurse["version"] == 4

        row = read_appointment(api, appointment["id"])
        assert row["schedule_status"] == ScheduleStatus.TENTATIVE
        assert row["chair_id"] is None
        assert row["nurse_id"] is None
        # Booking (1), the APPROVED readiness movement of PRD 3.6 (2), confirmation per
        # PRD 3.5 (3), then this demotion whose "version advances by one" (4).
        assert row["version"] == 4

    def test_both_load_figures_are_recomputed_while_the_window_survives(self, api):
        """The released chair's minutes and the released nurse's acuity both fall to zero,
        but the window the template built is not rebuilt by a demotion, and the payer
        coverage is untouched.

        Design: Corner/state_machines/nurse_going_inactive_demotes_the_confirmed_visit_and_clears_both_assignments
        """
        suite, appointment, _nurse = self._confirmed_visit_whose_nurse_goes_inactive(api)

        assert_committed_minutes(read_chair(api, suite.chair_id("A1")), 0)
        assert_assigned_acuity(read_nurse(api, suite.nurse_id), 0)

        row = read_appointment(api, appointment["id"])
        assert row["start_minute"] == 540
        assert row["end_minute"] == 780
        assert row["chair_minutes"] == 240
        assert row["acuity_points"] == 3

        approved, _meta = validate_paginated(
            api.list_authorization_requests(
                SCHEDULER, {"appointment_id": appointment["id"]}
            )
        )
        assert [request["status"] for request in approved] == [AuthStatus.APPROVED]


class TestSeatingAPatientBelongsToTheServiceDayAlone:
    """The same check-in call is refused on one calendar date and accepted on the next."""

    def _confirmed_the_day_before(self, api: ApiClient):
        suite, appointment = setup_confirmed_visit(
            api,
            clock="2026-08-09T09:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=START_MINUTE,
            with_lab=False,
        )
        return suite, appointment

    def test_a_day_early_is_refused_and_nothing_about_the_visit_moves(self, api):
        """The clock's UTC calendar date must equal the visit's service_date, so seating the
        patient a day early is refused outright, leaving the visit CONFIRMED on the version
        its confirmation gave it and the chair still holding its whole window.

        Design: Corner/state_machines/check_in_on_the_wrong_calendar_day_is_refused_before_the_chair_is_touched
        """
        suite, appointment = self._confirmed_the_day_before(api)

        response = api.check_in_appointment(appointment["id"], SCHEDULER)

        validate_error(response, ApiErrorId.ERR_CHECK_IN_WRONG_DAY, 409)

        row = read_appointment(api, appointment["id"])
        assert row["schedule_status"] == ScheduleStatus.CONFIRMED
        # Booking (1), the APPROVED readiness movement of PRD 3.6 (2), confirmation (3);
        # the refused check-in adds nothing.
        assert row["version"] == 3
        assert row["actual_start_minute"] is None
        assert_committed_minutes(read_chair(api, suite.chair_id("A1")), 240)

    def test_the_identical_call_is_accepted_once_the_clock_reaches_the_service_day(self, api):
        """Moving the clock forward is the only thing that changes, and the same call now
        seats the patient, advancing the visit's version by one while the start minute is
        still unstamped — that belongs to the infusion, not to the seat.

        Design: Corner/state_machines/check_in_on_the_wrong_calendar_day_is_refused_before_the_chair_is_touched
        """
        suite, appointment = self._confirmed_the_day_before(api)
        api.check_in_appointment(appointment["id"], SCHEDULER)

        set_clock(api, "2026-08-10T08:00:00Z")
        seated = validate_success(
            api.check_in_appointment(appointment["id"], SCHEDULER), 200
        )

        assert seated["schedule_status"] == ScheduleStatus.CHECKED_IN
        # Booking (1), the APPROVED readiness movement of PRD 3.6 (2), confirmation (3),
        # and the accepted seating (4).
        assert seated["version"] == 4
        assert seated["actual_start_minute"] is None
        assert_committed_minutes(read_chair(api, suite.chair_id("A1")), 240)


class TestASevereReactionHoldsTheDoorShutUntilTheReviewCloses:
    """A grade-three reaction lengthens the watch, blocks readiness, and bars the discharge
    through both of the review record's open statuses."""

    def _observing_visit_with_a_severe_reaction(self, api: ApiClient):
        suite, observing, prep = _chain_to_observing(api)
        event = record_reaction(api, observing["id"], suite.nurse_id, grade=3, action="HOLD")
        return suite, observing, prep, event

    def test_the_reaction_buys_an_extra_hour_of_watching_and_blocks_readiness(self, api):
        """A grade of three implies a full hour, and HOLD does not raise it further; the
        change in the visit's maximum extension is added to both the observation leg and the
        chair window, the end minute is recomputed, and the chair's committed minutes follow.

        Design: Corner/state_machines/discharge_is_guarded_by_the_open_grade_three_reaction_until_the_review_closes
        """
        suite, observing, _prep, event = self._observing_visit_with_a_severe_reaction(api)

        assert event["status"] == AdverseEventStatus.REPORTED
        assert event["observation_extension_minutes"] == 60

        row = read_appointment(api, observing["id"])
        assert row["observation_extension_minutes"] == 60
        assert row["observation_minutes"] == 120
        assert row["chair_minutes"] == 300
        assert row["end_minute"] == 840
        assert row["readiness_status"] == ReadinessStatus.BLOCKED

        assert_committed_minutes(read_chair(api, suite.chair_id("A1")), 300)

    def test_the_discharge_is_refused_through_both_open_review_statuses(self, api):
        """A patient with an unreviewed severe reaction is not sent home: the refusal stands
        while the record is REPORTED and stands again once a director has opened the review,
        because both statuses keep readiness BLOCKED.

        Design: Corner/state_machines/discharge_is_guarded_by_the_open_grade_three_reaction_until_the_review_closes
        """
        suite, observing, _prep, event = self._observing_visit_with_a_severe_reaction(api)

        validate_error(
            api.discharge_appointment(observing["id"], make_nurse_headers(suite.nurse_id)),
            ApiErrorId.ERR_ADVERSE_EVENT_OPEN,
            409,
        )

        under_review = open_review(api, event["id"])
        assert under_review["status"] == AdverseEventStatus.UNDER_REVIEW

        validate_error(
            api.discharge_appointment(observing["id"], make_nurse_headers(suite.nurse_id)),
            ApiErrorId.ERR_ADVERSE_EVENT_OPEN,
            409,
        )

        assert read_appointment(api, observing["id"])["schedule_status"] == (
            ScheduleStatus.OBSERVING
        )

    def test_closing_the_review_clears_the_bar_and_the_extension_is_kept(self, api):
        """Resuming on the same drug lifts readiness back to FULLY_CLEARED without moving the
        schedule dimension, the discharge then settles normally, and the extension already
        applied survives the settlement because a resolved reaction does not shorten the
        watching the patient needed.

        Design: Corner/state_machines/discharge_is_guarded_by_the_open_grade_three_reaction_until_the_review_closes
        """
        suite, observing, _prep, event = self._observing_visit_with_a_severe_reaction(api)
        open_review(api, event["id"])

        closed = close_review(api, event["id"], ReviewOutcome.RESUME_SAME_DRUG)
        assert closed["status"] == AdverseEventStatus.CLOSED

        cleared = read_appointment(api, observing["id"])
        assert cleared["readiness_status"] == ReadinessStatus.FULLY_CLEARED
        assert cleared["schedule_status"] == ScheduleStatus.OBSERVING

        set_clock(api, DISCHARGE_CLOCK)
        completed = discharge_visit(api, observing["id"], suite.nurse_id)

        assert completed["schedule_status"] == ScheduleStatus.COMPLETED
        assert completed["observation_extension_minutes"] == 60
        assert completed["billable_chair_units"] == 17
        assert read_plan(api, suite.plan_id)["status"] == PlanStatus.ACTIVE


class TestASwitchDispositionSuspendsTheRegimenAndAResumeLiftsIt:
    """ACTIVE to SUSPENDED to ACTIVE is a legal round trip, and the visits the suspension
    cancelled on the way out do not come back."""

    def _regimen_suspended_by_the_review(self, api: ApiClient):
        suite, observing, _prep = _chain_to_observing(
            api,
            chair_labels=("A1", "A2"),
            nurse_specs=[{"acuity_capacity_points": 12}],
        )
        later = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-17",
            requested_start_minute=540,
            cycle_number=2,
        )
        event = record_reaction(api, observing["id"], suite.nurse_id, grade=4, action="ABORT")
        open_review(api, event["id"])
        closed = close_review(api, event["id"], ReviewOutcome.SWITCH_BIOSIMILAR)
        return suite, observing, later, event, closed

    def test_the_switch_suspends_the_regimen_and_voids_the_next_cycle_for_free(self, api):
        """A grade-four reaction aborted at the bedside earns two full hours of watching, and
        the switch disposition pulls the whole regimen out of service: the cycle still sitting
        in TENTATIVE is cancelled at zero charge with both its seats released, while the visit
        that was actually running is well past TENTATIVE and stays where it is.

        Design: Corner/state_machines/plan_suspended_by_a_biosimilar_switch_review_cycles_back_to_active_on_resume
        """
        suite, observing, later, _event, closed = self._regimen_suspended_by_the_review(api)

        assert closed["observation_extension_minutes"] == 120

        plan = read_plan(api, suite.plan_id)
        assert plan["status"] == PlanStatus.SUSPENDED
        assert plan["version"] == 2

        voided = read_appointment(api, later["id"])
        assert voided["schedule_status"] == ScheduleStatus.CANCELLED
        assert voided["cancellation_charge_cents"] == 0
        assert voided["late_cancellation"] is False
        # PRD 3.11 governs what a cancellation does to the seats: chair_id and nurse_id are
        # "deliberately not cleared -- they remain as an audit trail of who was scheduled to
        # do the work", and what is released instead is the chair's committed_minutes and the
        # nurse's assigned_acuity_points, "because CANCELLED sits outside the committed set".
        assert voided["chair_id"] == later["chair_id"]
        assert voided["nurse_id"] == later["nurse_id"]
        assert_committed_minutes(read_chair(api, later["chair_id"]), 0)

        assert read_appointment(api, observing["id"])["schedule_status"] == (
            ScheduleStatus.OBSERVING
        )

    def test_the_resume_returns_the_regimen_to_active_without_resurrecting_anything(self, api):
        """A director lifts the suspension while the patient still reads SUITE — the system
        billed them nothing for a decision the system made — and the regimen becomes bookable
        again on a third version, but the cancelled cycle stays cancelled.

        Design: Corner/state_machines/plan_suspended_by_a_biosimilar_switch_review_cycles_back_to_active_on_resume
        """
        suite, _observing, later, _event, _closed = self._regimen_suspended_by_the_review(api)

        patient = read_patient(api, suite.patient_id)
        assert patient["waste_liability_cents"] == 0

        resumed = validate_success(
            api.resume_treatment_plan(
                suite.plan_id, make_resume_payload("Switched to the biosimilar line"), MEDICAL_DIRECTOR
            ),
            200,
        )

        assert resumed["status"] == PlanStatus.ACTIVE
        assert resumed["version"] == 3
        assert read_appointment(api, later["id"])["schedule_status"] == (
            ScheduleStatus.CANCELLED
        )
