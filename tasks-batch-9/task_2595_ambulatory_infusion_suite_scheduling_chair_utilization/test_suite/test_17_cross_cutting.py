"""The layers that only show up when several mechanisms are stacked on one request: the
three writes that legitimately supersede the row they address and therefore have nothing
but a version guard to protect them, the selector whose tie-breaks have to be walked in
the declared order, and the checkpoint whose counters describe one run rather than the
standing backlog."""

from test_helpers import (
    MEDICAL_DIRECTOR,
    PHARMACIST,
    SCHEDULER,
    ApiErrorId,
    BookingClass,
    LotStatus,
    PlanStatus,
    ScheduleStatus,
    SteeringStatus,
    UtilizationVariant,
    add_patient_with_plan,
    book_appointment,
    check_in_visit,
    complete_infusion,
    compound_dose,
    confirm_visit,
    create_drug,
    create_lot,
    discharge_visit,
    file_lab_result,
    make_lot_adjustment_payload,
    make_plan_revision_payload,
    make_reschedule_payload,
    read_appointment,
    read_chair,
    read_lot,
    read_nurse,
    read_patient,
    read_plan,
    read_utilization,
    request_dose,
    run_sweep,
    set_clock,
    setup_approved_authorization,
    setup_confirmed_visit,
    setup_suite,
    start_infusion,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2026-08-01T00:00:00Z"
SERVICE_DATE = "2026-08-10"
NEW_SERVICE_DATE = "2026-08-17"


class TestTheRescheduleGuardFiresBeforeTheSelector:
    """A reschedule is legal twice over — each move supersedes the visit before it — so no
    state precondition can tell a deliberate second move from one derived from a view that
    has since gone stale. The confirmation moves the row behind the client's back, and only
    the version guard notices."""

    def _stale_client_view(self, api):
        """A CONFIRMED visit whose client still holds the version the booking handed out."""
        suite = setup_suite(
            api, clock=SETUP_CLOCK, nurse_specs=[{"acuity_capacity_points": 12}]
        )
        booked = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
        )
        file_lab_result(api, suite.patient_id, collected_at=SETUP_CLOCK)
        setup_approved_authorization(api, booked["id"])
        confirm_visit(api, booked["id"])
        return suite, booked

    def _move(self, api, appointment_id, expected_version):
        return api.reschedule_appointment(
            appointment_id,
            make_reschedule_payload(
                expected_version,
                service_date=NEW_SERVICE_DATE,
                requested_start_minute=540,
                booking_class=BookingClass.ROUTINE,
            ),
            SCHEDULER,
        )

    def test_the_view_the_booking_handed_out_is_refused_without_touching_the_row(self, api):
        """The client replays the version it was given at booking, which the intervening
        confirmation has already moved on. The refusal has to land before the selector runs,
        so the visit keeps its day, its chair and its nurse.

        Design: Corner/cross_cutting_complexity_layers/reschedule_rejects_a_stale_appointment_version_then_accepts_the_current_one
        """
        suite, booked = self._stale_client_view(api)
        assert booked["version"] == 1

        stale = validate_error(
            self._move(api, booked["id"], booked["version"]),
            ApiErrorId.ERR_STALE_APPOINTMENT_VERSION,
            412,
        )
        assert stale["error_id"] != ApiErrorId.ERR_INVALID_SCHEDULE_STATE

        untouched = read_appointment(api, booked["id"])
        assert untouched["version"] > booked["version"]
        assert untouched["schedule_status"] == ScheduleStatus.CONFIRMED
        assert untouched["service_date"] == SERVICE_DATE
        assert untouched["start_minute"] == 540
        assert untouched["chair_id"] == suite.chair_id("A1")
        assert untouched["nurse_id"] == suite.nurse_id
        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3

    def test_the_retry_against_the_re_read_version_mints_the_replacement(self, api):
        """Re-reading the row and resubmitting the same move is accepted: the original
        retires at zero charge as a versioned write of its own, and the replacement points
        back at it and reclaims the chair the retirement had just released.

        Design: Corner/cross_cutting_complexity_layers/reschedule_rejects_a_stale_appointment_version_then_accepts_the_current_one
        """
        suite, booked = self._stale_client_view(api)
        validate_error(
            self._move(api, booked["id"], booked["version"]),
            ApiErrorId.ERR_STALE_APPOINTMENT_VERSION,
            412,
        )

        current = read_appointment(api, booked["id"])
        replacement = validate_success(
            self._move(api, booked["id"], current["version"]), 201
        )
        assert replacement["rescheduled_from_appointment_id"] == booked["id"]
        assert replacement["service_date"] == NEW_SERVICE_DATE
        assert replacement["start_minute"] == 540
        assert replacement["end_minute"] == 780
        assert replacement["version"] == 1
        assert replacement["schedule_status"] == ScheduleStatus.TENTATIVE
        assert replacement["cycle_number"] == booked["cycle_number"]
        assert replacement["chair_id"] == suite.chair_id("A1")

        original = read_appointment(api, booked["id"])
        assert original["schedule_status"] == ScheduleStatus.CANCELLED
        assert original["version"] == current["version"] + 1
        assert original["cancellation_charge_cents"] == 0
        assert original["late_cancellation"] is False

    def test_the_move_leaves_one_live_visit_rather_than_two(self, api):
        """Both halves of the supersede are visible in the derived figures: the vacated day
        reads empty while the chair and the nurse still carry exactly one occupancy.

        Design: Corner/cross_cutting_complexity_layers/reschedule_rejects_a_stale_appointment_version_then_accepts_the_current_one
        """
        suite, booked = self._stale_client_view(api)
        current = read_appointment(api, booked["id"])
        validate_success(self._move(api, booked["id"], current["version"]), 201)

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3

        vacated = read_utilization(
            api, suite.center_id, SERVICE_DATE, UtilizationVariant.SCHEDULED
        )
        assert vacated["utilization_pct"] == 0.00
        assert vacated["appointment_count"] == 0

        occupied = read_utilization(
            api, suite.center_id, NEW_SERVICE_DATE, UtilizationVariant.SCHEDULED
        )
        assert occupied["appointment_count"] == 1
        assert occupied["utilization_pct"] == 36.36

        rows, meta = validate_paginated(api.list_appointments(SCHEDULER))
        assert meta["total_count"] == 2
        assert sorted(row["schedule_status"] for row in rows) == [
            ScheduleStatus.CANCELLED,
            ScheduleStatus.TENTATIVE,
        ]


class TestTheLotGuardFiresBeforeTheUnitsArithmetic:
    """Two physical recounts are each individually legal, so a second adjustment derived
    from a pre-recount view would silently discard the first one's delta. The guard is a
    required input, and the refusal it produces must leave the units, the derived status
    and the version exactly where the accepted adjustment left them."""

    def _lot(self, api):
        set_clock(api, SETUP_CLOCK)
        drug = create_drug(api)
        lot = create_lot(
            api,
            drug["id"],
            lot_number="LOT-DEC",
            units_received=10,
            expires_on="2026-12-01T00:00:00Z",
        )
        return lot

    def test_the_version_guard_is_a_required_part_of_the_request(self, api):
        """An adjustment that names a delta and a reason but no observed version is not a
        soft-guarded write, it is a malformed one.

        Design: Corner/cross_cutting_complexity_layers/lot_adjustment_rejects_a_stale_lot_version_then_accepts_the_current_one
        """
        lot = self._lot(api)
        assert lot["version"] == 1
        assert lot["units_available"] == 10

        validate_error(
            api.create_lot_adjustment(
                lot["id"],
                {"units_delta": 5, "reason": "Second carton found in the fridge"},
                PHARMACIST,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            # PRD section 5 catalogues ERR_INVALID_REQUEST at HTTP 400.
            400,
        )

        unmoved = read_lot(api, lot["id"])
        assert unmoved["version"] == 1
        assert unmoved["units_received"] == 10
        assert unmoved["units_available"] == 10
        assert unmoved["status"] == LotStatus.AVAILABLE

    def test_the_second_recount_replaying_the_first_ones_view_is_refused(self, api):
        """The accepted receipt correction moved the lot to version 2; the shrinkage that
        still quotes version 1 would overwrite it, so it is refused with the units and the
        version left where the first adjustment put them.

        Design: Corner/cross_cutting_complexity_layers/lot_adjustment_rejects_a_stale_lot_version_then_accepts_the_current_one
        """
        lot = self._lot(api)
        first = validate_success(
            api.create_lot_adjustment(
                lot["id"],
                make_lot_adjustment_payload(
                    5, lot["version"], reason="Second carton found in the fridge"
                ),
                PHARMACIST,
            ),
        )
        assert first["version"] == 2
        assert first["units_received"] == 15
        assert first["units_available"] == 15

        stale = validate_error(
            api.create_lot_adjustment(
                lot["id"],
                make_lot_adjustment_payload(-3, lot["version"], reason="Breakage"),
                PHARMACIST,
            ),
            ApiErrorId.ERR_STALE_LOT_VERSION,
            412,
        )
        assert stale["error_id"] != ApiErrorId.ERR_INSUFFICIENT_DRUG_UNITS

        mid = read_lot(api, lot["id"])
        assert mid["version"] == 2
        assert mid["units_received"] == 15
        assert mid["units_available"] == 15
        assert mid["status"] == LotStatus.AVAILABLE

    def test_the_retry_applies_the_shrinkage_to_the_receipt_counter_alone(self, api):
        """Quoting the re-read version lets the shrinkage through, and it lands on
        units_received with units_available re-derived from it — the commitment, dispensing,
        waste and return counters are none of an adjustment's business.

        Design: Corner/cross_cutting_complexity_layers/lot_adjustment_rejects_a_stale_lot_version_then_accepts_the_current_one
        """
        lot = self._lot(api)
        validate_success(
            api.create_lot_adjustment(
                lot["id"],
                make_lot_adjustment_payload(
                    5, lot["version"], reason="Second carton found in the fridge"
                ),
                PHARMACIST,
            ),
        )
        validate_error(
            api.create_lot_adjustment(
                lot["id"],
                make_lot_adjustment_payload(-3, lot["version"], reason="Breakage"),
                PHARMACIST,
            ),
            ApiErrorId.ERR_STALE_LOT_VERSION,
            412,
        )

        current = read_lot(api, lot["id"])
        second = validate_success(
            api.create_lot_adjustment(
                lot["id"],
                make_lot_adjustment_payload(-3, current["version"], reason="Breakage"),
                PHARMACIST,
            ),
        )
        assert second["version"] == 3
        assert second["units_received"] == 12
        assert second["units_available"] == 12
        assert second["status"] == LotStatus.AVAILABLE
        for counter in (
            "units_committed",
            "units_administered",
            "units_wasted",
            "units_returned",
        ):
            assert second[counter] == 0
        assert read_lot(api, lot["id"])["units_available"] == 12


class TestThePlanGuardFiresBeforeTheSupersedeCascade:
    """The regimen's version does not move because anybody edited the regimen — it moves
    because a discharge at the bedside rolled the cycle counters into it. A director who
    read the dose before the first infusion and files a revision afterwards is therefore
    working from a stale view, and the guard is what stops the counters being reset."""

    def _finished_first_cycle(self, api):
        """Cycle 1 of a six-cycle regimen carried all the way to COMPLETED."""
        suite, appointment = setup_confirmed_visit(
            api,
            clock="2026-08-10T08:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            lab_collected_at="2026-08-10T07:00:00Z",
            nurse_specs=[{"acuity_capacity_points": 12}],
        )
        create_lot(api, suite.drug_id, units_received=10)
        check_in_visit(api, appointment["id"])

        set_clock(api, "2026-08-10T08:30:00Z")
        requested = request_dose(api, appointment["id"], units_requested=1)
        compound_dose(api, requested["id"])

        set_clock(api, "2026-08-10T09:00:00Z")
        start_infusion(api, appointment["id"], suite.nurse_id)
        set_clock(api, "2026-08-10T11:30:00Z")
        complete_infusion(api, appointment["id"], suite.nurse_id)
        set_clock(api, "2026-08-10T13:15:00Z")
        completed = discharge_visit(api, appointment["id"], suite.nurse_id)
        return suite, completed

    def _revision(self, api, plan_id, expected_version):
        return api.create_plan_revision(
            plan_id,
            make_plan_revision_payload(
                expected_version, dose_mg_per_kg=12, total_cycles=6, premed_waived=False
            ),
            MEDICAL_DIRECTOR,
        )

    def test_the_creation_time_view_is_stale_once_the_discharge_has_written_the_row(
        self, api
    ):
        """The refusal has to land ahead of the supersede cascade, so the regimen is still
        ACTIVE afterwards and still carries the cycle the infusion actually delivered.

        Design: Corner/cross_cutting_complexity_layers/plan_revision_rejects_a_stale_plan_version_then_accepts_the_current_one
        """
        suite, completed = self._finished_first_cycle(api)
        assert completed["schedule_status"] == ScheduleStatus.COMPLETED
        assert suite.plan["version"] == 1

        validate_error(
            self._revision(api, suite.plan_id, suite.plan["version"]),
            ApiErrorId.ERR_STALE_PLAN_VERSION,
            412,
        )

        mid = read_plan(api, suite.plan_id)
        assert mid["version"] > suite.plan["version"]
        assert mid["status"] == PlanStatus.ACTIVE
        assert mid["completed_cycles"] == 1
        assert mid["first_dose_completed"] is True
        assert mid["dose_mg_per_kg"] == 10

        _rows, meta = validate_paginated(
            api.list_treatment_plans(SCHEDULER, {"supersedes_plan_id": suite.plan_id})
        )
        assert meta["total_count"] == 0

    def test_the_retry_supersedes_cleanly_and_leaves_the_finished_visit_alone(self, api):
        """Filing the same revision against the re-read version is accepted: the successor
        is minted ACTIVE at the new dose, the predecessor is retired one version higher, and
        the visit that is already settled is not part of the cancellation cascade.

        Design: Corner/cross_cutting_complexity_layers/plan_revision_rejects_a_stale_plan_version_then_accepts_the_current_one
        """
        suite, completed = self._finished_first_cycle(api)
        validate_error(
            self._revision(api, suite.plan_id, suite.plan["version"]),
            ApiErrorId.ERR_STALE_PLAN_VERSION,
            412,
        )

        mid = read_plan(api, suite.plan_id)
        successor = validate_success(
            self._revision(api, suite.plan_id, mid["version"]), 201
        )
        assert successor["status"] == PlanStatus.ACTIVE
        assert successor["supersedes_plan_id"] == suite.plan_id
        assert successor["dose_mg_per_kg"] == 12
        assert successor["total_cycles"] == 6
        assert successor["patient_id"] == suite.patient_id
        assert successor["version"] == 1

        retired = read_plan(api, suite.plan_id)
        assert retired["status"] == PlanStatus.SUPERSEDED
        assert retired["version"] == mid["version"] + 1

        assert (
            read_appointment(api, completed["id"])["schedule_status"]
            == ScheduleStatus.COMPLETED
        )

        rows, meta = validate_paginated(
            api.list_treatment_plans(SCHEDULER, {"supersedes_plan_id": suite.plan_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == successor["id"]


class TestTheSelectorWalksItsRankingKeysInTheDeclaredOrder:
    """The chairs are created A3, A1, A2 so that label order and insertion order disagree,
    and the roster is hired so that hire order and carried load disagree once the first
    visit lands. Four bookings then walk the keys one at a time."""

    def _three_chairs_and_two_nurses(self, api):
        suite = setup_suite(
            api,
            clock=SETUP_CLOCK,
            chair_labels=("A3", "A1", "A2"),
            nurse_specs=[
                {"acuity_capacity_points": 12},
                {"acuity_capacity_points": 12},
            ],
        )
        regimens = [(suite.patient, suite.plan)]
        for ordinal in (2, 3, 4):
            regimens.append(
                add_patient_with_plan(
                    api, suite, f"MRN-000{ordinal}", full_name=f"Pat {ordinal}"
                )
            )
        return suite, regimens

    def _book(self, api, suite, regimen, minute):
        patient, plan = regimen
        return book_appointment(
            api,
            suite.center_id,
            patient["id"],
            plan["id"],
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=minute,
        )

    def test_an_all_tied_pool_is_resolved_by_label_and_the_roster_by_hire_order(self, api):
        """Nothing is loaded yet, so the chairs tie on committed minutes and the label decides
        against the insertion order, while the nurses tie on load and the hire order decides.

        Design: Corner/cross_cutting_complexity_layers/the_selector_ranking_keys_are_applied_in_the_declared_order
        """
        suite, regimens = self._three_chairs_and_two_nurses(api)

        first = self._book(api, suite, regimens[0], 540)
        assert first["start_minute"] == 540
        assert first["chair_minutes"] == 240
        assert first["acuity_points"] == 3
        assert first["chair_id"] == suite.chair_id("A1")
        assert first["chair_id"] != suite.chair_id("A3")
        assert first["nurse_id"] == suite.nurses[0]["id"]

    def test_the_load_keys_take_over_once_the_first_visit_is_seated(self, api):
        """The second booking finds A1 buffer-blocked and the first nurse carrying three
        points, so the label key picks A2 over A3 while the load key overrules hire order; the
        third has one chair left and a roster back in a tie.

        Design: Corner/cross_cutting_complexity_layers/the_selector_ranking_keys_are_applied_in_the_declared_order
        """
        suite, regimens = self._three_chairs_and_two_nurses(api)
        self._book(api, suite, regimens[0], 540)

        second = self._book(api, suite, regimens[1], 540)
        assert second["start_minute"] == 540
        assert second["chair_id"] == suite.chair_id("A2")
        assert second["nurse_id"] == suite.nurses[1]["id"]

        third = self._book(api, suite, regimens[2], 540)
        assert third["start_minute"] == 540
        assert third["chair_id"] == suite.chair_id("A3")
        assert third["nurse_id"] == suite.nurses[0]["id"]

    def test_a_fresh_band_returns_to_the_label_key_while_the_roster_does_not_tie(self, api):
        """By the afternoon band every chair is free again and all three carry the same
        committed minutes, so the label decides a second time; the nurses do not tie, so the
        load key decides even though neither of them is busy at that hour.

        Design: Corner/cross_cutting_complexity_layers/the_selector_ranking_keys_are_applied_in_the_declared_order
        """
        suite, regimens = self._three_chairs_and_two_nurses(api)
        for regimen in regimens[:3]:
            self._book(api, suite, regimen, 540)

        fourth = self._book(api, suite, regimens[3], 900)
        assert fourth["start_minute"] == 900
        assert fourth["end_minute"] == 1140
        assert fourth["chair_id"] == suite.chair_id("A1")
        assert fourth["nurse_id"] == suite.nurses[1]["id"]

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 480
        assert read_chair(api, suite.chair_id("A2"))["committed_minutes"] == 240
        assert read_chair(api, suite.chair_id("A3"))["committed_minutes"] == 240
        assert read_nurse(api, suite.nurses[0]["id"])["assigned_acuity_points"] == 6
        assert read_nurse(api, suite.nurses[1]["id"])["assigned_acuity_points"] == 6


class TestTheCheckpointCountsOneRunAndNotTheBacklog:
    """A checkpoint run reports what that run changed. Sweeping one minute early expires the
    lot and no visit, sweeping at the exact grace instant reports the no-show and no lot,
    sweeping again at the same clock is a pure no-op, and a later run catches only the visit
    whose own grace has since elapsed."""

    def _two_visits_and_an_expiring_lot(self, api):
        suite = setup_suite(
            api, clock=SETUP_CLOCK, nurse_specs=[{"acuity_capacity_points": 12}]
        )
        lot = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-AUG",
            units_received=10,
            expires_on="2026-08-10T00:00:00Z",
        )
        other_patient, other_plan = add_patient_with_plan(
            api, suite, "MRN-0002", full_name="Pat Two"
        )
        morning = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
        )
        afternoon = book_appointment(
            api,
            suite.center_id,
            other_patient["id"],
            other_plan["id"],
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=900,
        )
        return suite, lot, morning, afternoon, other_patient

    def test_one_minute_short_of_the_grace_edge_expires_the_lot_alone(self, api):
        """At 09:29 the morning visit has had twenty-nine of its thirty minutes, so the run
        reports the lot it did expire and no no-show at all.

        Design: Corner/cross_cutting_complexity_layers/the_daily_sweep_is_a_per_run_checkpoint_with_an_inclusive_no_show_edge
        """
        suite, lot, morning, afternoon, _other = self._two_visits_and_an_expiring_lot(api)
        assert lot["status"] == LotStatus.AVAILABLE
        assert morning["start_minute"] == 540
        assert afternoon["start_minute"] == 900

        set_clock(api, "2026-08-10T09:29:00Z")
        first_run = run_sweep(api, suite.center_id, SERVICE_DATE)
        assert first_run["expired_lot_count"] == 1
        assert first_run["expired_authorization_count"] == 0
        assert first_run["wasted_preparation_count"] == 0
        assert first_run["no_show_count"] == 0

        lapsed = read_lot(api, lot["id"])
        assert lapsed["status"] == LotStatus.EXPIRED
        assert lapsed["units_received"] == 10
        assert lapsed["units_available"] == 10
        assert read_appointment(api, morning["id"])["schedule_status"] == (
            ScheduleStatus.TENTATIVE
        )

    def test_the_edge_is_inclusive_and_a_repeat_run_writes_nothing(self, api):
        """One minute later the grace has elapsed to the minute, and the lot is not counted a
        second time because it is no longer in the status the step selects. Running again on
        the same clock reports four zeroes and does not touch the row it already moved.

        Design: Corner/cross_cutting_complexity_layers/the_daily_sweep_is_a_per_run_checkpoint_with_an_inclusive_no_show_edge
        """
        suite, lot, morning, afternoon, _other = self._two_visits_and_an_expiring_lot(api)
        set_clock(api, "2026-08-10T09:29:00Z")
        run_sweep(api, suite.center_id, SERVICE_DATE)

        set_clock(api, "2026-08-10T09:30:00Z")
        second_run = run_sweep(api, suite.center_id, SERVICE_DATE)
        assert second_run["no_show_count"] == 1
        assert second_run["expired_lot_count"] == 0

        after_second = read_appointment(api, morning["id"])
        assert after_second["schedule_status"] == ScheduleStatus.NO_SHOW

        third_run = run_sweep(api, suite.center_id, SERVICE_DATE)
        assert third_run["expired_lot_count"] == 0
        assert third_run["expired_authorization_count"] == 0
        assert third_run["wasted_preparation_count"] == 0
        assert third_run["no_show_count"] == 0
        assert read_appointment(api, morning["id"])["version"] == after_second["version"]
        assert read_appointment(api, afternoon["id"])["schedule_status"] == (
            ScheduleStatus.TENTATIVE
        )

    def test_the_afternoon_visit_waits_for_its_own_grace_to_elapse(self, api):
        """The fourth run sits exactly thirty minutes past the afternoon start, so it reports
        that one visit and nothing else; both patients end the day one strike down with their
        slots released and their steering unchanged.

        Design: Corner/cross_cutting_complexity_layers/the_daily_sweep_is_a_per_run_checkpoint_with_an_inclusive_no_show_edge
        """
        suite, lot, morning, afternoon, other = self._two_visits_and_an_expiring_lot(api)
        set_clock(api, "2026-08-10T09:29:00Z")
        run_sweep(api, suite.center_id, SERVICE_DATE)
        set_clock(api, "2026-08-10T09:30:00Z")
        run_sweep(api, suite.center_id, SERVICE_DATE)
        run_sweep(api, suite.center_id, SERVICE_DATE)

        set_clock(api, "2026-08-10T15:30:00Z")
        fourth_run = run_sweep(api, suite.center_id, SERVICE_DATE)
        assert fourth_run["no_show_count"] == 1
        assert fourth_run["expired_lot_count"] == 0

        assert read_appointment(api, morning["id"])["schedule_status"] == (
            ScheduleStatus.NO_SHOW
        )
        assert read_appointment(api, afternoon["id"])["schedule_status"] == (
            ScheduleStatus.NO_SHOW
        )

        for patient_id in (suite.patient_id, other["id"]):
            struck = read_patient(api, patient_id)
            assert struck["no_show_strikes"] == 1
            assert struck["steering_status"] == SteeringStatus.SUITE

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 0
