"""Whole endpoints read as endpoints: the partial patch that leaves the rest of the row
alone, the action that answers a row once, the bulk call whose scope is deliberately
split, the derived foreign keys, the repeatable computed read, and the guard that
depends on the shape of the row the write would leave behind."""

from test_helpers import (
    MEDICAL_DIRECTOR,
    AUTH_SPECIALIST,
    ApiErrorId,
    AuthStatus,
    ChairStatus,
    NurseStatus,
    PreparationStatus,
    ReadinessStatus,
    ReminderChannel,
    ReminderOutcome,
    SCHEDULER,
    ScheduleStatus,
    assert_instant_equals,
    book_appointment,
    check_in_visit,
    compound_dose,
    confirm_visit,
    complete_infusion,
    create_center,
    create_chair,
    create_drug,
    create_lot,
    create_nurse,
    create_patient,
    create_plan,
    create_template,
    discharge_visit,
    make_chair_payload,
    make_reminder_response_payload,
    read_appointment,
    read_center,
    read_chair,
    read_chair_billing,
    is_iso8601_timestamp,
    read_nurse,
    read_patient,
    read_preparation,
    record_reminder,
    request_dose,
    run_sweep,
    set_clock,
    setup_approved_authorization,
    setup_booked_visit,
    setup_confirmed_visit,
    setup_suite,
    start_infusion,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2026-08-01T00:00:00Z"
PATCH_CLOCK = "2026-08-02T00:00:00Z"
SERVICE_DATE = "2026-08-10"


class TestTheRosterPatchTouchesOneFieldAndTheRestOfTheRowStands:
    """A four-field optional patch, and the roster listing that a status change reshapes
    without ever deleting a row."""

    def _roster(self, api):
        set_clock(api, SETUP_CLOCK)
        home = create_center(api, name="Home Suite")
        away = create_center(api, name="Away Suite")
        first = create_nurse(api, home["id"])
        second = create_nurse(api, home["id"], full_name="Nils Bak", status=None)
        third = create_nurse(api, away["id"], full_name="Nadia Cruz")
        return home, away, first, second, third

    def test_the_roster_row_reports_its_declared_shift_and_an_empty_load(self, api):
        """A nurse is read back with the capacity and shift bounds that were declared, a
        load of zero, and the roster status the omitted input defaulted to.

        Design: Corner/endpoints/nurse_crud_round_trip_patches_one_field_and_leaves_the_rest_of_the_roster_row_intact
        """
        home, away, first, second, third = self._roster(api)

        row = read_nurse(api, first["id"])
        assert row["full_name"] == "Nora Ade"
        assert row["acuity_capacity_points"] == 6
        assert row["assigned_acuity_points"] == 0
        assert row["shift_start_minute"] == 480
        assert row["shift_end_minute"] == 1140
        assert row["status"] == NurseStatus.ACTIVE
        assert row["center_id"] == home["id"]
        assert row["version"] == 1
        # PRD 2.5 fixes the audit instants' format and says updated_at is "refreshed on
        # every mutation of the row"; it never names the clock that mints them, so only
        # the insert-time equality is asserted here.
        assert is_iso8601_timestamp(row["created_at"])
        assert row["updated_at"] == row["created_at"]

        assert read_nurse(api, second["id"])["status"] == NurseStatus.ACTIVE
        assert read_nurse(api, third["id"])["center_id"] == away["id"]

    def test_patching_the_capacity_alone_leaves_the_name_shift_and_status_alone(self, api):
        """The request carries one field, so the other three keep the values they were
        created with while the row's version and stamp move on.

        Design: Corner/endpoints/nurse_crud_round_trip_patches_one_field_and_leaves_the_rest_of_the_roster_row_intact
        """
        home, away, first, second, third = self._roster(api)

        set_clock(api, PATCH_CLOCK)
        patched = validate_success(
            api.update_nurse(first["id"], {"acuity_capacity_points": 9}, SCHEDULER)
        )

        assert patched["acuity_capacity_points"] == 9
        assert patched["full_name"] == "Nora Ade"
        assert patched["shift_start_minute"] == 480
        assert patched["shift_end_minute"] == 1140
        assert patched["status"] == NurseStatus.ACTIVE
        assert patched["assigned_acuity_points"] == 0
        assert patched["version"] == 2
        # PRD 2.5: the mutation refreshes updated_at while created_at stands.
        assert patched["created_at"] == first["created_at"]
        assert patched["updated_at"] != patched["created_at"]

    def test_the_deactivated_nurse_leaves_the_active_listing_but_not_the_record(self, api):
        """The listing is filterable on centre and roster status only, so deactivating a
        nurse hides them from an ACTIVE listing while the row itself is still readable
        by id and still counted by the unfiltered listing.

        Design: Corner/endpoints/nurse_crud_round_trip_patches_one_field_and_leaves_the_rest_of_the_roster_row_intact
        """
        home, away, first, second, third = self._roster(api)

        rows, meta = validate_paginated(
            api.list_nurses(
                SCHEDULER, {"center_id": home["id"], "status": NurseStatus.ACTIVE}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert third["id"] not in {row["id"] for row in rows}

        deactivated = validate_success(
            api.update_nurse(second["id"], {"status": NurseStatus.INACTIVE}, SCHEDULER)
        )
        assert deactivated["status"] == NurseStatus.INACTIVE

        rows, meta = validate_paginated(
            api.list_nurses(
                SCHEDULER, {"center_id": home["id"], "status": NurseStatus.ACTIVE}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

        assert read_nurse(api, second["id"])["id"] == second["id"]

        rows, meta = validate_paginated(
            api.list_nurses(SCHEDULER, {"center_id": home["id"]})
        )
        assert meta["total_count"] == 2
        assert third["id"] not in {row["id"] for row in rows}


class TestTheOutreachAnswerIsRecordedOnceAndOnlyOnce:
    """The action mutates the contact it addresses, leaves the visit alone, and refuses a
    second answer even when the answer is identical."""

    def _contacted_visit(self, api):
        suite, appointment = setup_booked_visit(
            api,
            clock=SETUP_CLOCK,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
        )
        contact = record_reminder(api, appointment["id"], channel=ReminderChannel.SMS)
        return suite, appointment, contact

    def test_the_new_contact_starts_unanswered_at_the_first_sequence_number(self, api):
        """Outreach is recorded before the patient has said anything, so the row is born
        awaiting an answer.

        Design: Corner/endpoints/the_reminder_response_action_records_one_outcome_and_refuses_a_second_answer
        """
        suite, appointment, contact = self._contacted_visit(api)

        assert contact["outcome"] == ReminderOutcome.NO_RESPONSE
        assert contact["sequence_number"] == 1
        assert contact["appointment_id"] == appointment["id"]
        assert contact["patient_id"] == suite.patient_id

    def test_the_patient_answers_in_place_and_the_visit_is_untouched(self, api):
        """Answering mutates the contact that was addressed rather than adding a second
        one, and an attendance confirmation has no scheduling consequence at all.

        Design: Corner/endpoints/the_reminder_response_action_records_one_outcome_and_refuses_a_second_answer
        """
        suite, appointment, contact = self._contacted_visit(api)

        answered = validate_success(
            api.respond_to_reminder(
                contact["id"],
                make_reminder_response_payload(ReminderOutcome.CONFIRM_ATTENDANCE),
                suite.patient_headers,
            ),
            200,
        )
        assert answered["id"] == contact["id"]
        assert answered["outcome"] == ReminderOutcome.CONFIRM_ATTENDANCE

        rows, meta = validate_paginated(
            api.list_reminder_contacts(SCHEDULER, {"appointment_id": appointment["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == contact["id"]

        still_booked = read_appointment(api, appointment["id"])
        assert still_booked["schedule_status"] == ScheduleStatus.TENTATIVE
        assert still_booked["chair_id"] == suite.chair_id("A1")

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_patient(api, suite.patient_id)["no_show_strikes"] == 0

    def test_a_second_answer_is_refused_rather_than_treated_as_a_repeat(self, api):
        """The guard is the contact's own outcome, so even the very same answer sent again
        is a conflict and not a silent no-op.

        Design: Corner/endpoints/the_reminder_response_action_records_one_outcome_and_refuses_a_second_answer
        """
        suite, appointment, contact = self._contacted_visit(api)

        validate_success(
            api.respond_to_reminder(
                contact["id"],
                make_reminder_response_payload(ReminderOutcome.CONFIRM_ATTENDANCE),
                suite.patient_headers,
            ),
            200,
        )

        again = api.respond_to_reminder(
            contact["id"],
            make_reminder_response_payload(ReminderOutcome.CONFIRM_ATTENDANCE),
            SCHEDULER,
        )
        validate_error(again, ApiErrorId.ERR_REMINDER_ALREADY_ANSWERED, 409)

        rows, meta = validate_paginated(
            api.list_reminder_contacts(SCHEDULER, {"appointment_id": appointment["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["outcome"] == ReminderOutcome.CONFIRM_ATTENDANCE

        still_booked = read_appointment(api, appointment["id"])
        assert still_booked["schedule_status"] == ScheduleStatus.TENTATIVE
        assert still_booked["chair_id"] == suite.chair_id("A1")


class TestOneSweepIsGlobalForThreeStepsAndCentreScopedForTheFourth:
    """Two centres sharing one product and one lot, and the four counters that expose
    where each step of the checkpoint looked."""

    def _two_centres(self, api):
        set_clock(api, SETUP_CLOCK)
        home = create_center(api, name="Home Suite")
        away = create_center(api, name="Away Suite")
        home_chair = create_chair(api, home["id"], "H1")
        away_chair = create_chair(api, away["id"], "W1")
        home_nurse = create_nurse(api, home["id"])
        away_nurse = create_nurse(api, away["id"], full_name="Nils Bak")
        drug = create_drug(api)
        create_lot(
            api,
            drug["id"],
            units_received=10,
            expires_on="2026-08-11T00:00:00Z",
        )
        home_template = create_template(api, home["id"], drug["id"])
        away_template = create_template(api, away["id"], drug["id"])
        home_patient = create_patient(api, mrn="MRN-0001", full_name="Pat Home")
        away_patient = create_patient(api, mrn="MRN-0002", full_name="Pat Away")
        home_plan = create_plan(api, home_patient["id"], drug["id"])
        away_plan = create_plan(api, away_patient["id"], drug["id"])

        visits = {}
        preps = {}
        for key, center, template, patient, plan in (
            ("home", home, home_template, home_patient, home_plan),
            ("away", away, away_template, away_patient, away_plan),
        ):
            visit = book_appointment(
                api,
                center["id"],
                patient["id"],
                plan["id"],
                template["id"],
                service_date=SERVICE_DATE,
                requested_start_minute=540,
            )
            setup_approved_authorization(api, visit["id"])
            visits[key] = confirm_visit(api, visit["id"])

        set_clock(api, "2026-08-10T08:30:00Z")
        for key in ("home", "away"):
            requested = request_dose(api, visits[key]["id"], units_requested=1)
            preps[key] = compound_dose(api, requested["id"])

        set_clock(api, "2026-08-12T00:00:00Z")
        return {
            "home": home,
            "away": away,
            "home_chair": home_chair,
            "away_chair": away_chair,
            "home_nurse": home_nurse,
            "away_nurse": away_nurse,
            "home_patient": home_patient,
            "away_patient": away_patient,
            "visits": visits,
            "preps": preps,
        }

    def test_the_home_sweep_wastes_both_doses_but_only_its_own_visit_no_shows(self, api):
        """Expiring the lot and wasting stale doses look everywhere, while marking a
        no-show looks only at the centre named in the path.

        Design: Corner/endpoints/one_sweep_call_is_global_for_the_first_three_steps_and_center_scoped_for_the_fourth
        """
        estate = self._two_centres(api)

        report = run_sweep(api, estate["home"]["id"], SERVICE_DATE)

        assert report["expired_lot_count"] == 1
        assert report["expired_authorization_count"] == 0
        assert report["wasted_preparation_count"] == 2
        assert report["no_show_count"] == 1

        for key in ("home", "away"):
            wasted = read_preparation(api, estate["preps"][key]["id"])
            assert wasted["status"] == PreparationStatus.WASTED
            assert wasted["waste_cost_cents"] == 90000

        assert (
            read_appointment(api, estate["visits"]["home"]["id"])["schedule_status"]
            == ScheduleStatus.NO_SHOW
        )
        assert (
            read_appointment(api, estate["visits"]["away"]["id"])["schedule_status"]
            == ScheduleStatus.CONFIRMED
        )

    def test_the_away_sweep_finds_the_global_work_done_and_marks_its_own_visit(self, api):
        """The second call reports zero for the three global steps, because each of them
        selects only rows still sitting in the pre-transition status, and still marks the
        visit its own centre owns.

        Design: Corner/endpoints/one_sweep_call_is_global_for_the_first_three_steps_and_center_scoped_for_the_fourth
        """
        estate = self._two_centres(api)

        run_sweep(api, estate["home"]["id"], SERVICE_DATE)
        second = run_sweep(api, estate["away"]["id"], SERVICE_DATE)

        assert second["expired_lot_count"] == 0
        assert second["expired_authorization_count"] == 0
        assert second["wasted_preparation_count"] == 0
        assert second["no_show_count"] == 1

        assert (
            read_appointment(api, estate["visits"]["away"]["id"])["schedule_status"]
            == ScheduleStatus.NO_SHOW
        )
        assert read_patient(api, estate["home_patient"]["id"])["no_show_strikes"] == 1
        assert read_patient(api, estate["away_patient"]["id"])["no_show_strikes"] == 1
        assert read_chair(api, estate["home_chair"]["id"])["committed_minutes"] == 0
        assert read_chair(api, estate["away_chair"]["id"])["committed_minutes"] == 0


class TestTheCoverageRequestDerivesBothOfItsParents:
    """The body names only the payer, so neither foreign key can be aimed at the wrong
    row, and the two filters separate by visit while uniting by regimen."""

    def _two_cycles(self, api):
        suite = setup_suite(
            api,
            clock=SETUP_CLOCK,
            chair_labels=("A1", "A2"),
            nurse_specs=[{"acuity_capacity_points": 12}],
        )
        first = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
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
        return suite, first, second

    def test_the_request_takes_its_visit_from_the_path_and_its_regimen_from_the_visit(
        self, api
    ):
        """A caller supplies a payer name and nothing else, so the visit comes from the
        path and the regimen is copied off that visit.

        Design: Corner/endpoints/an_authorization_request_copies_the_regimen_link_and_is_findable_by_either_parent
        """
        suite, first, second = self._two_cycles(api)

        coverage = validate_success(
            api.create_authorization_request(
                first["id"], {"payer_name": "Northwind Health"}, SCHEDULER
            ),
            201,
        )

        assert coverage["status"] == AuthStatus.DRAFT
        assert coverage["submission_count"] == 0
        assert coverage["appointment_id"] == first["id"]
        assert coverage["treatment_plan_id"] == suite.plan_id
        assert coverage["payer_name"] == "Northwind Health"

        assert (
            read_appointment(api, first["id"])["readiness_status"]
            == ReadinessStatus.PENDING
        )

    def test_two_visits_of_one_regimen_split_by_visit_and_gather_by_regimen(self, api):
        """Both requests carry the same regimen link, which is exactly what makes the
        regimen filter a history read while the visit filter stays a single-visit read.

        Design: Corner/endpoints/an_authorization_request_copies_the_regimen_link_and_is_findable_by_either_parent
        """
        suite, first, second = self._two_cycles(api)

        first_coverage = validate_success(
            api.create_authorization_request(
                first["id"], {"payer_name": "Northwind Health"}, SCHEDULER
            ),
            201,
        )
        second_coverage = validate_success(
            api.create_authorization_request(
                second["id"], {"payer_name": "Meridian Mutual"}, AUTH_SPECIALIST
            ),
            201,
        )
        assert second_coverage["treatment_plan_id"] == suite.plan_id
        assert second_coverage["appointment_id"] == second["id"]

        rows, meta = validate_paginated(
            api.list_authorization_requests(
                AUTH_SPECIALIST, {"appointment_id": first["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_coverage["id"]

        rows, meta = validate_paginated(
            api.list_authorization_requests(
                MEDICAL_DIRECTOR, {"treatment_plan_id": suite.plan_id}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            first_coverage["id"],
            second_coverage["id"],
        }

    def test_the_payer_and_status_filters_narrow_the_history_to_one_row(self, api):
        """Combining the payer filter with the status filter picks out the one request that
        satisfies both.

        Design: Corner/endpoints/an_authorization_request_copies_the_regimen_link_and_is_findable_by_either_parent
        """
        suite, first, second = self._two_cycles(api)

        validate_success(
            api.create_authorization_request(
                first["id"], {"payer_name": "Northwind Health"}, SCHEDULER
            ),
            201,
        )
        second_coverage = validate_success(
            api.create_authorization_request(
                second["id"], {"payer_name": "Meridian Mutual"}, AUTH_SPECIALIST
            ),
            201,
        )

        rows, meta = validate_paginated(
            api.list_authorization_requests(
                SCHEDULER,
                {"payer_name": "Meridian Mutual", "status": AuthStatus.DRAFT},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == second_coverage["id"]


class TestTheChairBillingReadIsRepeatableAndChangesNothing:
    """A computed read of a settled day, taken three times, and an unbooked day that
    answers with zeros instead of a missing resource."""

    def _settled_day(self, api):
        suite, appointment = setup_confirmed_visit(
            api,
            clock="2026-08-10T08:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            lab_collected_at="2026-08-10T07:00:00Z",
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

    def test_the_day_reports_the_units_the_visit_settled_on(self, api):
        """The figures come from the row written at discharge — a 255-minute occupancy
        billed as seventeen quarter-hours — rather than being recomputed by the read.

        Design: Corner/endpoints/the_chair_billing_read_is_repeatable_and_mutates_nothing_it_reports_on
        """
        suite, completed = self._settled_day(api)

        assert completed["schedule_status"] == ScheduleStatus.COMPLETED
        assert completed["actual_start_minute"] == 540
        assert completed["actual_end_minute"] == 795
        assert completed["billable_chair_units"] == 17

        report = read_chair_billing(api, suite.center_id, SERVICE_DATE)
        assert report["completed_appointment_count"] == 1
        assert report["day_billable_units"] == 17
        assert report["day_billable_cents"] == 153000
        assert report["service_date"] == SERVICE_DATE
        assert report["center_id"] == suite.center_id

    def test_three_reads_agree_with_each_other_and_move_no_version(self, api):
        """Reading the summary twice under two different roles returns the same body, and
        the visit it reports on is left exactly as discharge left it.

        Design: Corner/endpoints/the_chair_billing_read_is_repeatable_and_mutates_nothing_it_reports_on
        """
        suite, completed = self._settled_day(api)
        settled_version = completed["version"]

        first = read_chair_billing(api, suite.center_id, SERVICE_DATE)
        second = validate_success(
            api.get_chair_billing_summary(
                suite.center_id, MEDICAL_DIRECTOR, {"service_date": SERVICE_DATE}
            )
        )

        assert second["completed_appointment_count"] == first["completed_appointment_count"]
        assert second["day_billable_units"] == first["day_billable_units"]
        assert second["day_billable_cents"] == first["day_billable_cents"]

        after_reads = read_appointment(api, completed["id"])
        assert after_reads["version"] == settled_version
        assert after_reads["billable_chair_units"] == 17
        assert after_reads["schedule_status"] == ScheduleStatus.COMPLETED

    def test_a_day_with_nothing_settled_on_it_reports_zeros(self, api):
        """The service date is a filter rather than a resource, so a day nobody was booked
        on is an ordinary answer of zeros.

        Design: Corner/endpoints/the_chair_billing_read_is_repeatable_and_mutates_nothing_it_reports_on
        """
        suite, completed = self._settled_day(api)

        empty = read_chair_billing(api, suite.center_id, "2026-08-11")
        assert empty["completed_appointment_count"] == 0
        assert empty["day_billable_units"] == 0
        assert empty["day_billable_cents"] == 0
        assert empty["service_date"] == "2026-08-11"


class TestTheForbiddenChairPairingIsJudgedOnTheResultingRow:
    """The guard reads the row the write would leave behind, so the identical request body
    is illegal one moment and legal the next."""

    def _reserved_chair(self, api):
        set_clock(api, SETUP_CLOCK)
        center = create_center(api, urgent_reserve_chair_count=1)
        chair = create_chair(api, center["id"], "R1", reserved_for_urgent=True)
        return center, chair

    def test_the_pairing_is_refused_at_creation_too(self, api):
        """A chair may not be born out of service and reserved at the same time, and the
        refusal leaves the centre's derived counts untouched.

        Design: Corner/endpoints/a_chair_patch_is_refused_only_when_the_resulting_row_would_be_out_of_service_and_urgent_reserved
        """
        center, chair = self._reserved_chair(api)

        assert chair["status"] == ChairStatus.AVAILABLE
        assert chair["reserved_for_urgent"] is True

        response = api.create_chair(
            make_chair_payload(
                center["id"],
                "R2",
                status=ChairStatus.OUT_OF_SERVICE,
                reserved_for_urgent=True,
            ),
            SCHEDULER,
        )
        validate_error(response, ApiErrorId.ERR_CHAIR_OUT_OF_SERVICE, 409)

        rows, meta = validate_paginated(
            api.list_chairs(SCHEDULER, {"center_id": center["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == chair["id"]

        estate = read_center(api, center["id"])
        assert estate["available_chair_count"] == 1
        assert estate["reserved_chair_count"] == 1

    def test_the_same_patch_body_is_refused_and_then_accepted(self, api):
        """Taking a reserved chair out of service is a conflict that does not even bump the
        version, yet the very same request succeeds once the flag has been cleared.

        Design: Corner/endpoints/a_chair_patch_is_refused_only_when_the_resulting_row_would_be_out_of_service_and_urgent_reserved
        """
        center, chair = self._reserved_chair(api)

        refused = api.update_chair(
            chair["id"], {"status": ChairStatus.OUT_OF_SERVICE}, SCHEDULER
        )
        validate_error(refused, ApiErrorId.ERR_CHAIR_OUT_OF_SERVICE, 409)
        assert read_chair(api, chair["id"])["version"] == chair["version"]

        cleared = validate_success(
            api.update_chair(chair["id"], {"reserved_for_urgent": False}, SCHEDULER)
        )
        assert cleared["reserved_for_urgent"] is False
        assert cleared["version"] == 2

        withdrawn = validate_success(
            api.update_chair(
                chair["id"], {"status": ChairStatus.OUT_OF_SERVICE}, SCHEDULER
            )
        )
        assert withdrawn["status"] == ChairStatus.OUT_OF_SERVICE
        assert withdrawn["version"] == 3

        estate = read_center(api, center["id"])
        assert estate["available_chair_count"] == 0
        assert estate["reserved_chair_count"] == 0

    def test_reserving_a_chair_that_is_already_out_of_service_is_refused_as_well(self, api):
        """The mirrored order of the same two-field combination is refused too, so neither
        field can be used to sneak the pairing in.

        Design: Corner/endpoints/a_chair_patch_is_refused_only_when_the_resulting_row_would_be_out_of_service_and_urgent_reserved
        """
        center, chair = self._reserved_chair(api)

        validate_success(
            api.update_chair(chair["id"], {"reserved_for_urgent": False}, SCHEDULER)
        )
        validate_success(
            api.update_chair(
                chair["id"], {"status": ChairStatus.OUT_OF_SERVICE}, SCHEDULER
            )
        )

        response = api.update_chair(
            chair["id"], {"reserved_for_urgent": True}, SCHEDULER
        )
        validate_error(response, ApiErrorId.ERR_CHAIR_OUT_OF_SERVICE, 409)

        final = read_chair(api, chair["id"])
        assert final["reserved_for_urgent"] is False
        assert final["status"] == ChairStatus.OUT_OF_SERVICE

        rows, meta = validate_paginated(
            api.list_chairs(SCHEDULER, {"center_id": center["id"]})
        )
        assert meta["total_count"] == 1
