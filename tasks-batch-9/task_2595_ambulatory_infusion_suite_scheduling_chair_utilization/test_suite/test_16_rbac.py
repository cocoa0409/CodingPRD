"""Six walled-off roles seen from both sides: the relay in which every hand-off must be
accepted, the matrix in which no actor may reach a peer's exclusive work, the operations
that genuinely accept either peer, and the two roles whose authority is bounded by the
identity of a row they own."""

from test_helpers import (
    AUTH_SPECIALIST,
    MEDICAL_DIRECTOR,
    PHARMACIST,
    SCHEDULER,
    AdverseEventStatus,
    ApiErrorId,
    AuthStatus,
    DoseTier,
    LabResultStatus,
    PlanStatus,
    PreparationStatus,
    ReadinessStatus,
    ReminderChannel,
    ReminderOutcome,
    ReviewOutcome,
    ScheduleStatus,
    TemplateStatus,
    UtilizationVariant,
    book_appointment,
    check_in_visit,
    compound_dose,
    create_center,
    create_chair,
    create_drug,
    create_lot,
    create_nurse,
    create_patient,
    create_plan,
    create_template,
    file_authorization,
    make_adverse_event_payload,
    make_appointment_payload,
    make_approval_decision_payload,
    make_authorization_payload,
    make_cancel_payload,
    make_close_review_payload,
    make_lab_result_payload,
    make_lot_adjustment_payload,
    make_nurse_headers,
    make_patient_headers,
    make_preparation_payload,
    make_reminder_payload,
    make_reminder_response_payload,
    make_resume_payload,
    make_template_payload,
    make_treatment_plan_payload,
    read_appointment,
    read_chair,
    read_lot,
    read_nurse,
    read_plan,
    read_reminder,
    request_dose,
    set_clock,
    setup_confirmed_visit,
    setup_suite,
    start_infusion,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2026-08-01T00:00:00Z"
SERVICE_DATE = "2026-08-10"


class TestAllSixRolesCarryOneVisitBetweenThem:
    """No single actor can walk a visit from booking to the closed review, so the whole
    relay has to be accepted hand-off by hand-off — this is the positive control for every
    denial elsewhere in this file."""

    def _relay(self, api):
        set_clock(api, SETUP_CLOCK)
        center = create_center(api)
        chair = create_chair(api, center["id"], "A1")
        nurse = create_nurse(api, center["id"])
        patient = create_patient(api)
        drug = create_drug(api)
        create_lot(api, drug["id"], units_received=10)
        plan = create_plan(api, patient["id"], drug["id"])
        template = create_template(api, center["id"], drug["id"])
        appointment = book_appointment(
            api,
            center["id"],
            patient["id"],
            plan["id"],
            template["id"],
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )

        auth = validate_success(
            api.create_authorization_request(
                appointment["id"], make_authorization_payload(), AUTH_SPECIALIST
            ),
            201,
        )
        submitted = validate_success(
            api.submit_authorization(auth["id"], AUTH_SPECIALIST)
        )
        decided = validate_success(
            api.decide_authorization(
                auth["id"], make_approval_decision_payload(1), AUTH_SPECIALIST
            )
        )
        confirmed = validate_success(
            api.confirm_appointment(appointment["id"], SCHEDULER)
        )
        reminder = validate_success(
            api.create_reminder(
                appointment["id"], make_reminder_payload(ReminderChannel.SMS), SCHEDULER
            ),
            201,
        )
        answered = validate_success(
            api.respond_to_reminder(
                reminder["id"],
                make_reminder_response_payload(ReminderOutcome.CONFIRM_ATTENDANCE),
                make_patient_headers(patient["id"]),
            )
        )

        set_clock(api, "2026-08-10T08:30:00Z", PHARMACIST)
        drawn = validate_success(
            api.create_lab_result(
                make_lab_result_payload(
                    patient["id"], "2026-08-10T06:00:00Z", 2.0, 150
                ),
                make_nurse_headers(nurse["id"]),
            ),
            201,
        )
        requested = validate_success(
            api.create_drug_preparation(
                appointment["id"], make_preparation_payload(1), PHARMACIST
            ),
            201,
        )
        prepared = validate_success(api.prepare_dose(requested["id"], PHARMACIST))
        checked_in = validate_success(
            api.check_in_appointment(appointment["id"], make_nurse_headers(nurse["id"]))
        )

        set_clock(api, "2026-08-10T09:00:00Z", SCHEDULER)
        infusing = validate_success(
            api.start_infusion(appointment["id"], make_nurse_headers(nurse["id"]))
        )
        event = validate_success(
            api.create_adverse_event(
                appointment["id"],
                make_adverse_event_payload(2, "SLOW_RATE"),
                make_nurse_headers(nurse["id"]),
            ),
            201,
        )
        reviewing = validate_success(
            api.start_adverse_event_review(event["id"], MEDICAL_DIRECTOR)
        )
        closed = validate_success(
            api.close_adverse_event(
                event["id"],
                make_close_review_payload(ReviewOutcome.RESUME_SAME_DRUG),
                MEDICAL_DIRECTOR,
            )
        )
        risk = validate_success(
            api.get_no_show_risk(patient["id"], make_patient_headers(patient["id"]))
        )
        return {
            "appointment": appointment,
            "submitted": submitted,
            "decided": decided,
            "confirmed": confirmed,
            "answered": answered,
            "drawn": drawn,
            "prepared": prepared,
            "checked_in": checked_in,
            "infusing": infusing,
            "event": event,
            "reviewing": reviewing,
            "closed": closed,
            "risk": risk,
        }

    def test_the_payer_desk_and_the_front_desk_hand_the_visit_along(self, api):
        """Submission and the payer's answer belong to the authorization desk alone, the
        commitment to the front desk, and the answer to the outreach to the patient — four
        actors, four accepted calls.

        Design: Corner/rbac/all_six_roles_execute_their_own_exclusive_operations_in_one_relay
        """
        relay = self._relay(api)

        assert relay["submitted"]["status"] == AuthStatus.SUBMITTED
        assert relay["decided"]["status"] == AuthStatus.APPROVED
        assert relay["confirmed"]["schedule_status"] == ScheduleStatus.CONFIRMED
        assert relay["answered"]["outcome"] == ReminderOutcome.CONFIRM_ATTENDANCE

    def test_the_pharmacy_and_the_chair_side_split_the_service_day(self, api):
        """The draw is shared between pharmacy and the bedside, compounding is pharmacy's
        alone, check-in is shared, and the infusion itself belongs to the nurse.

        Design: Corner/rbac/all_six_roles_execute_their_own_exclusive_operations_in_one_relay
        """
        relay = self._relay(api)

        assert relay["drawn"]["status"] == LabResultStatus.RESULTED
        assert relay["prepared"]["status"] == PreparationStatus.PREPARED
        assert relay["checked_in"]["schedule_status"] == ScheduleStatus.CHECKED_IN
        assert relay["infusing"]["schedule_status"] == ScheduleStatus.INFUSING
        assert relay["event"]["observation_extension_minutes"] == 30

    def test_governance_disposes_of_the_reaction_and_the_patient_reads_their_own_row(
        self, api
    ):
        """The review is the director's exclusive surface, the risk figure is the patient's
        own self-service read, and the milder reaction has already lengthened the window.

        Design: Corner/rbac/all_six_roles_execute_their_own_exclusive_operations_in_one_relay
        """
        relay = self._relay(api)

        assert relay["reviewing"]["status"] == AdverseEventStatus.UNDER_REVIEW
        assert relay["closed"]["status"] == AdverseEventStatus.CLOSED

        assert relay["risk"]["score"] == 0.0
        assert relay["risk"]["reminder_tier"] == "STANDARD"

        watched = read_appointment(api, relay["appointment"]["id"])
        assert watched["observation_minutes"] == 90
        assert watched["chair_minutes"] == 270


class TestNoPeerRoleReachesAnotherPeersExclusiveWork:
    """Ten calls that each carry the wrong credential, three of which would also have failed
    on state or on the concurrency guard — so the identifier proves which check ran first."""

    def _standing_fixture(self, api):
        suite = setup_suite(api, clock=SETUP_CLOCK)
        lot = create_lot(api, suite.drug_id, units_received=10)
        appointment = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )
        auth = file_authorization(api, appointment["id"])
        prep = request_dose(api, appointment["id"], units_requested=1)
        return suite, lot, appointment, auth, prep

    def test_the_exclusive_creates_are_closed_to_every_other_role(self, api):
        """Booking, stocking, submitting, compounding, confirming and sweeping each belong to
        exactly one role, and the five wrong actors are all told the same thing.

        Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
        """
        suite, lot, appointment, auth, prep = self._standing_fixture(api)

        pharmacist_books = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-17",
                requested_start_minute=540,
                cycle_number=2,
            ),
            PHARMACIST,
        )
        validate_error(pharmacist_books, ApiErrorId.ERR_UNAUTHORIZED, 403)

        scheduler_stocks = api.create_drug_lot(
            {
                "drug_id": suite.drug_id,
                "lot_number": "LOT-NOV",
                "units_received": 5,
                "expires_on": "2026-11-01T00:00:00Z",
            },
            SCHEDULER,
        )
        validate_error(scheduler_stocks, ApiErrorId.ERR_UNAUTHORIZED, 403)

        nurse_submits = api.submit_authorization(
            auth["id"], make_nurse_headers(suite.nurse_id)
        )
        validate_error(nurse_submits, ApiErrorId.ERR_UNAUTHORIZED, 403)

        director_compounds = api.prepare_dose(prep["id"], MEDICAL_DIRECTOR)
        validate_error(director_compounds, ApiErrorId.ERR_UNAUTHORIZED, 403)

        director_confirms = api.confirm_appointment(appointment["id"], MEDICAL_DIRECTOR)
        validate_error(director_confirms, ApiErrorId.ERR_UNAUTHORIZED, 403)

        patient_books = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-24",
                requested_start_minute=540,
                cycle_number=3,
            ),
            make_patient_headers(suite.patient_id),
        )
        validate_error(patient_books, ApiErrorId.ERR_UNAUTHORIZED, 403)

        pharmacist_sweeps = api.run_daily_sweep(
            suite.center_id, {"service_date": SERVICE_DATE}, PHARMACIST
        )
        validate_error(pharmacist_sweeps, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_the_role_check_runs_ahead_of_state_and_ahead_of_the_version_guard(self, api):
        """Each of these three calls would have failed anyway — the visit is only tentative,
        the regimen is not suspended, the lot version is correct — and each still answers on
        the credential instead.

        Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
        """
        suite, lot, appointment, auth, prep = self._standing_fixture(api)

        scheduler_infuses = api.start_infusion(appointment["id"], SCHEDULER)
        wrong_role = validate_error(scheduler_infuses, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert wrong_role["error_id"] != ApiErrorId.ERR_INVALID_SCHEDULE_STATE

        specialist_resumes = api.resume_treatment_plan(
            suite.plan_id, make_resume_payload("Not my call to make"), AUTH_SPECIALIST
        )
        validate_error(specialist_resumes, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert read_plan(api, suite.plan_id)["status"] == PlanStatus.ACTIVE

        specialist_adjusts = api.create_lot_adjustment(
            lot["id"],
            make_lot_adjustment_payload(
                # The version the guard would accept, so the refusal can only be the
                # credential: the fixture's dose request advanced the lot past its
                # stocking-time snapshot.
                5,
                read_lot(api, lot["id"])["version"],
                reason="Unauthorised recount",
            ),
            AUTH_SPECIALIST,
        )
        before_occ = validate_error(specialist_adjusts, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert before_occ["error_id"] != ApiErrorId.ERR_STALE_LOT_VERSION

    def test_not_one_refused_call_leaves_a_trace(self, api):
        """Ten denials and the database is exactly as the fixture left it: no row created, no
        counter moved, no version advanced.

        Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
        """
        suite, lot, appointment, auth, prep = self._standing_fixture(api)
        # The fixture's dose request already moved the lot's committed counters, and a
        # recomputation of a derived counter is itself a mutation that advances the row's
        # version, so the baseline the denials are measured against is the lot as the
        # fixture left it rather than the snapshot taken at stocking time.
        baseline_lot = read_lot(api, lot["id"])

        api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-17",
                requested_start_minute=540,
                cycle_number=2,
            ),
            PHARMACIST,
        )
        api.create_drug_lot(
            {
                "drug_id": suite.drug_id,
                "lot_number": "LOT-NOV",
                "units_received": 5,
                "expires_on": "2026-11-01T00:00:00Z",
            },
            SCHEDULER,
        )
        api.start_infusion(appointment["id"], SCHEDULER)
        api.resume_treatment_plan(
            suite.plan_id, make_resume_payload("Not my call to make"), AUTH_SPECIALIST
        )
        api.create_lot_adjustment(
            lot["id"],
            make_lot_adjustment_payload(
                5, baseline_lot["version"], reason="Unauthorised recount"
            ),
            AUTH_SPECIALIST,
        )

        unchanged = read_appointment(api, appointment["id"])
        assert unchanged["schedule_status"] == ScheduleStatus.TENTATIVE
        assert unchanged["version"] == appointment["version"]

        still_stocked = read_lot(api, lot["id"])
        assert still_stocked["units_received"] == 10
        assert still_stocked["units_available"] == 9
        assert still_stocked["version"] == baseline_lot["version"]

        untouched = read_plan(api, suite.plan_id)
        assert untouched["status"] == PlanStatus.ACTIVE

        lots, lot_meta = validate_paginated(api.list_drug_lots(PHARMACIST, {}))
        assert lot_meta["total_count"] == 1

        visits, visit_meta = validate_paginated(api.list_appointments(SCHEDULER, {}))
        assert visit_meta["total_count"] == 1


class TestTheSharedOperationsAcceptEitherPeerAndWriteTheSameRow:
    """Four shared write pairs and one shared computed read, each reached from both sides."""

    def _shared_fixture(self, api):
        set_clock(api, SETUP_CLOCK)
        center = create_center(api)
        chair = create_chair(api, center["id"], "A1")
        nurse = create_nurse(api, center["id"])
        drug = create_drug(api)
        template = validate_success(
            api.create_template(
                make_template_payload(center["id"], drug["id"], DoseTier.MID), SCHEDULER
            ),
            201,
        )
        patient_one = create_patient(api, mrn="MRN-0001", full_name="Pat One")
        patient_two = create_patient(api, mrn="MRN-0002", full_name="Pat Two")
        plan_one = validate_success(
            api.create_treatment_plan(
                make_treatment_plan_payload(patient_one["id"], drug["id"]), SCHEDULER
            ),
            201,
        )
        first = book_appointment(
            api,
            center["id"],
            patient_one["id"],
            plan_one["id"],
            template["id"],
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )
        second = book_appointment(
            api,
            center["id"],
            patient_one["id"],
            plan_one["id"],
            template["id"],
            service_date="2026-08-17",
            requested_start_minute=540,
            cycle_number=2,
        )
        return {
            "center": center,
            "chair": chair,
            "nurse": nurse,
            "drug": drug,
            "template": template,
            "patient_one": patient_one,
            "patient_two": patient_two,
            "plan_one": plan_one,
            "first": first,
            "second": second,
        }

    def _scheduled_utilization(self, api, center_id, headers, service_date=SERVICE_DATE):
        return validate_success(
            api.get_utilization(
                center_id,
                headers,
                {"service_date": service_date, "variant": UtilizationVariant.SCHEDULED},
            )
        )

    def test_either_peer_creates_the_row_and_either_peer_bumps_the_version(self, api):
        """The pharmacy builds a template the front desk could equally have built, the two
        resnapshots compose to a third version whichever peer issues them, and the director's
        regimen is the same row the front desk's is.

        Design: Corner/rbac/shared_operations_accept_either_peer_and_write_the_identical_row
        """
        fixture = self._shared_fixture(api)

        high = validate_success(
            api.create_template(
                make_template_payload(
                    fixture["center"]["id"], fixture["drug"]["id"], DoseTier.HIGH
                ),
                PHARMACIST,
            ),
            201,
        )
        assert high["status"] == TemplateStatus.ACTIVE
        assert high["base_admin_minutes"] == 120
        assert high["acuity_points"] == 3

        by_pharmacy = validate_success(
            api.update_template(
                fixture["template"]["id"], {"resnapshot": True}, PHARMACIST
            )
        )
        assert by_pharmacy["version"] == 2
        by_front_desk = validate_success(
            api.update_template(
                fixture["template"]["id"], {"resnapshot": True}, SCHEDULER
            )
        )
        assert by_front_desk["version"] == 3

        by_director = validate_success(
            api.create_treatment_plan(
                make_treatment_plan_payload(
                    fixture["patient_two"]["id"], fixture["drug"]["id"]
                ),
                MEDICAL_DIRECTOR,
            ),
            201,
        )
        assert by_director["status"] == PlanStatus.ACTIVE
        assert fixture["plan_one"]["status"] == PlanStatus.ACTIVE

        rows, meta = validate_paginated(api.list_templates(SCHEDULER, {}))
        assert meta["total_count"] == 2
        assert sorted(row["dose_tier"] for row in rows) == [DoseTier.HIGH, DoseTier.MID]

    def test_the_shared_computed_read_does_not_vary_by_its_reader(self, api):
        """One booked visit against one chair's service day, reported field for field the
        same to the front desk and to the director.

        Design: Corner/rbac/shared_operations_accept_either_peer_and_write_the_identical_row
        """
        fixture = self._shared_fixture(api)
        center_id = fixture["center"]["id"]

        for_front_desk = self._scheduled_utilization(api, center_id, SCHEDULER)
        for_director = self._scheduled_utilization(api, center_id, MEDICAL_DIRECTOR)

        assert for_front_desk == for_director
        assert for_front_desk["available_chair_minutes"] == 660
        assert for_front_desk["appointment_count"] == 1
        assert for_front_desk["utilization_pct"] == 36.36

    def test_the_patient_and_the_front_desk_answer_and_cancel_identically(self, api):
        """The patient answering their own text message and the front desk recording the
        voice answer are one write; so are the two cancellations, both far enough out to
        carry no charge, and both release the chair.

        Design: Corner/rbac/shared_operations_accept_either_peer_and_write_the_identical_row
        """
        fixture = self._shared_fixture(api)
        owner = make_patient_headers(fixture["patient_one"]["id"])

        first_reminder = validate_success(
            api.create_reminder(
                fixture["first"]["id"],
                make_reminder_payload(ReminderChannel.SMS),
                SCHEDULER,
            ),
            201,
        )
        by_patient = validate_success(
            api.respond_to_reminder(
                first_reminder["id"],
                make_reminder_response_payload(ReminderOutcome.CONFIRM_ATTENDANCE),
                owner,
            )
        )
        second_reminder = validate_success(
            api.create_reminder(
                fixture["second"]["id"],
                make_reminder_payload(ReminderChannel.VOICE),
                SCHEDULER,
            ),
            201,
        )
        by_front_desk = validate_success(
            api.respond_to_reminder(
                second_reminder["id"],
                make_reminder_response_payload(ReminderOutcome.CONFIRM_ATTENDANCE),
                SCHEDULER,
            )
        )
        assert by_patient["outcome"] == ReminderOutcome.CONFIRM_ATTENDANCE
        assert by_front_desk["outcome"] == ReminderOutcome.CONFIRM_ATTENDANCE

        patient_cancel = validate_success(
            api.cancel_appointment(
                fixture["first"]["id"], owner, make_cancel_payload("Patient self-cancel")
            )
        )
        desk_cancel = validate_success(
            api.cancel_appointment(
                fixture["second"]["id"],
                SCHEDULER,
                make_cancel_payload("Front-desk cancel"),
            )
        )
        assert patient_cancel["schedule_status"] == ScheduleStatus.CANCELLED
        assert desk_cancel["schedule_status"] == ScheduleStatus.CANCELLED
        assert patient_cancel["cancellation_charge_cents"] == 0
        assert desk_cancel["cancellation_charge_cents"] == 0

        emptied = self._scheduled_utilization(api, fixture["center"]["id"], SCHEDULER)
        assert emptied["utilization_pct"] == 0.0
        assert read_chair(api, fixture["chair"]["id"])["committed_minutes"] == 0
        assert read_nurse(api, fixture["nurse"]["id"])["assigned_acuity_points"] == 0


class TestOneNurseCannotActOnAnotherNursesAssignment:
    """The role opens the endpoint; the identity of the assigned nurse decides who may use
    it — and reads are deliberately outside that second layer."""

    def _visit_with_a_second_nurse_on_the_roster(self, api):
        suite, appointment = setup_confirmed_visit(
            api,
            clock="2026-08-10T08:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            lab_collected_at="2026-08-10T07:00:00Z",
        )
        create_lot(api, suite.drug_id, units_received=10)

        set_clock(api, "2026-08-10T08:30:00Z")
        requested = request_dose(api, appointment["id"], units_requested=1)
        compound_dose(api, requested["id"])
        checked_in = check_in_visit(api, appointment["id"])

        other = create_nurse(api, suite.center_id, full_name="Nils Second")
        set_clock(api, "2026-08-10T09:00:00Z")
        return suite, appointment, checked_in, other

    def test_the_unassigned_nurse_holds_the_role_and_fails_only_the_identity_match(
        self, api
    ):
        """A colleague with the very same role is refused on the assignment rather than on
        the credential, and may still read the row she is not allowed to touch.

        Design: Corner/rbac/a_nurse_cannot_act_on_another_nurses_chair_side_assignment
        """
        suite, appointment, checked_in, other = (
            self._visit_with_a_second_nurse_on_the_roster(api)
        )
        assert checked_in["nurse_id"] == suite.nurse_id

        response = api.start_infusion(
            appointment["id"], make_nurse_headers(other["id"])
        )
        error = validate_error(response, ApiErrorId.ERR_NURSE_NOT_ASSIGNED, 403)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED

        readable = validate_success(
            api.get_appointment(appointment["id"], make_nurse_headers(other["id"]))
        )
        assert readable["schedule_status"] == ScheduleStatus.CHECKED_IN

    def test_every_chair_side_write_is_bound_and_not_merely_the_first(self, api):
        """Once the assigned nurse has started the infusion, the colleague is still walled
        off from the reaction record and from ending the administration leg.

        Design: Corner/rbac/a_nurse_cannot_act_on_another_nurses_chair_side_assignment
        """
        suite, appointment, checked_in, other = (
            self._visit_with_a_second_nurse_on_the_roster(api)
        )

        started = validate_success(
            api.start_infusion(appointment["id"], make_nurse_headers(suite.nurse_id))
        )
        assert started["schedule_status"] == ScheduleStatus.INFUSING

        reaction = api.create_adverse_event(
            appointment["id"],
            make_adverse_event_payload(2, "SLOW_RATE"),
            make_nurse_headers(other["id"]),
        )
        validate_error(reaction, ApiErrorId.ERR_NURSE_NOT_ASSIGNED, 403)

        completion = api.complete_infusion(
            appointment["id"], make_nurse_headers(other["id"])
        )
        validate_error(completion, ApiErrorId.ERR_NURSE_NOT_ASSIGNED, 403)

        assert (
            read_appointment(api, appointment["id"])["schedule_status"]
            == ScheduleStatus.INFUSING
        )

    def test_the_reporting_nurse_is_taken_from_the_header(self, api):
        """The reaction is stamped with the acting nurse's own identifier, so the colleague's
        name can never appear on a record she could not have written.

        Design: Corner/rbac/a_nurse_cannot_act_on_another_nurses_chair_side_assignment
        """
        suite, appointment, checked_in, other = (
            self._visit_with_a_second_nurse_on_the_roster(api)
        )
        validate_success(
            api.start_infusion(appointment["id"], make_nurse_headers(suite.nurse_id))
        )

        recorded = validate_success(
            api.create_adverse_event(
                appointment["id"],
                make_adverse_event_payload(2, "SLOW_RATE"),
                make_nurse_headers(suite.nurse_id),
            ),
            201,
        )
        assert recorded["reported_by_nurse_id"] == suite.nurse_id

        rows, meta = validate_paginated(
            api.list_adverse_events(
                MEDICAL_DIRECTOR, {"reported_by_nurse_id": other["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestOnePatientCannotAddressAnothersRecords:
    """Four addressed rows that plainly exist, refused as a non-owner and not as missing —
    while the same actor's own rows stay perfectly reachable."""

    def _two_patients(self, api):
        set_clock(api, SETUP_CLOCK)
        center = create_center(api)
        chair = create_chair(api, center["id"], "A1")
        nurse = create_nurse(api, center["id"], acuity_capacity_points=12)
        drug = create_drug(api)
        template = create_template(api, center["id"], drug["id"])

        first_patient = create_patient(api, mrn="MRN-0001", full_name="Pat One")
        second_patient = create_patient(api, mrn="MRN-0002", full_name="Pat Two")
        first_plan = create_plan(api, first_patient["id"], drug["id"])
        second_plan = create_plan(api, second_patient["id"], drug["id"])

        first_visit = book_appointment(
            api,
            center["id"],
            first_patient["id"],
            first_plan["id"],
            template["id"],
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )
        second_visit = book_appointment(
            api,
            center["id"],
            second_patient["id"],
            second_plan["id"],
            template["id"],
            service_date="2026-08-11",
            requested_start_minute=540,
            cycle_number=1,
        )
        reminder = validate_success(
            api.create_reminder(
                second_visit["id"],
                make_reminder_payload(ReminderChannel.SMS),
                SCHEDULER,
            ),
            201,
        )
        return {
            "chair": chair,
            "nurse": nurse,
            "first_patient": first_patient,
            "second_patient": second_patient,
            "first_visit": first_visit,
            "second_visit": second_visit,
            "reminder": reminder,
        }

    def test_the_cross_patient_reads_are_refused_as_a_non_owner_and_not_as_missing(
        self, api
    ):
        """Three addressed rows and one computed read, all belonging to somebody else — and
        the front desk reads the same patient row in the same fixture, so nothing here is a
        missing-row answer in disguise.

        Design: Corner/rbac/a_patient_cannot_address_another_patients_visit_reminder_or_record
        """
        fixture = self._two_patients(api)
        intruder = make_patient_headers(fixture["first_patient"]["id"])
        stranger = fixture["second_patient"]["id"]

        validate_error(
            api.get_patient(stranger, intruder), ApiErrorId.ERR_PATIENT_NOT_OWNER, 403
        )
        validate_error(
            api.get_no_show_risk(stranger, intruder),
            ApiErrorId.ERR_PATIENT_NOT_OWNER,
            403,
        )
        validate_error(
            api.get_appointment(fixture["second_visit"]["id"], intruder),
            ApiErrorId.ERR_PATIENT_NOT_OWNER,
            403,
        )
        validate_error(
            api.get_reminder_contact(fixture["reminder"]["id"], intruder),
            ApiErrorId.ERR_PATIENT_NOT_OWNER,
            403,
        )

        by_staff = validate_success(api.get_patient(stranger, SCHEDULER))
        assert by_staff["mrn"] == "MRN-0002"

    def test_the_cross_patient_writes_are_refused_and_leave_the_rows_alone(self, api):
        """Answering somebody else's reminder and cancelling somebody else's visit are both
        refused, and neither row moves.

        Design: Corner/rbac/a_patient_cannot_address_another_patients_visit_reminder_or_record
        """
        fixture = self._two_patients(api)
        intruder = make_patient_headers(fixture["first_patient"]["id"])

        validate_error(
            api.respond_to_reminder(
                fixture["reminder"]["id"],
                make_reminder_response_payload(ReminderOutcome.CANCEL_REQUEST),
                intruder,
            ),
            ApiErrorId.ERR_PATIENT_NOT_OWNER,
            403,
        )
        validate_error(
            api.cancel_appointment(
                fixture["second_visit"]["id"],
                intruder,
                make_cancel_payload("Not my appointment"),
            ),
            ApiErrorId.ERR_PATIENT_NOT_OWNER,
            403,
        )

        untouched = read_appointment(api, fixture["second_visit"]["id"])
        assert untouched["schedule_status"] == ScheduleStatus.TENTATIVE

        unanswered = read_reminder(api, fixture["reminder"]["id"])
        assert unanswered["outcome"] == ReminderOutcome.NO_RESPONSE
        assert unanswered["sequence_number"] == 1

    def test_the_owner_still_reaches_their_own_record_and_their_own_visit(self, api):
        """This is scoping and not a blanket denial: the same credential reads its own patient
        row and cancels its own visit, releasing only its own chair minutes.

        Design: Corner/rbac/a_patient_cannot_address_another_patients_visit_reminder_or_record
        """
        fixture = self._two_patients(api)
        owner = make_patient_headers(fixture["first_patient"]["id"])

        own_row = validate_success(
            api.get_patient(fixture["first_patient"]["id"], owner)
        )
        assert own_row["mrn"] == "MRN-0001"

        own_cancel = validate_success(
            api.cancel_appointment(
                fixture["first_visit"]["id"],
                owner,
                make_cancel_payload("Own visit, own decision"),
            )
        )
        assert own_cancel["schedule_status"] == ScheduleStatus.CANCELLED

        assert read_chair(api, fixture["chair"]["id"])["committed_minutes"] == 240

        rows, meta = validate_paginated(api.list_appointments(SCHEDULER, {}))
        assert meta["total_count"] == 2


class TestTheReportingNurseNeverDisposesOfHerOwnReaction:
    """The bedside record and its disposition are split between two roles on purpose, and
    neither half can reach the other."""

    def _severe_reaction(self, api):
        suite, appointment = setup_confirmed_visit(
            api,
            clock="2026-08-10T08:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            lab_collected_at="2026-08-10T07:00:00Z",
        )
        create_lot(api, suite.drug_id, units_received=10)

        set_clock(api, "2026-08-10T08:30:00Z")
        requested = request_dose(api, appointment["id"], units_requested=1)
        compound_dose(api, requested["id"])
        check_in_visit(api, appointment["id"])

        set_clock(api, "2026-08-10T09:00:00Z")
        start_infusion(api, appointment["id"], suite.nurse_id)

        set_clock(api, "2026-08-10T09:40:00Z")
        event = validate_success(
            api.create_adverse_event(
                appointment["id"],
                make_adverse_event_payload(3, "ABORT"),
                make_nurse_headers(suite.nurse_id),
            ),
            201,
        )
        return suite, appointment, event

    def test_the_reporter_can_neither_open_nor_close_the_review_of_her_own_event(
        self, api
    ):
        """The nurse who was at the chair is stamped onto the record and is then walled off
        from judging it.

        Design: Corner/rbac/the_reporting_nurse_cannot_review_or_close_her_own_reaction
        """
        suite, appointment, event = self._severe_reaction(api)

        assert event["reported_by_nurse_id"] == suite.nurse_id
        assert event["observation_extension_minutes"] == 60

        nurse_headers = make_nurse_headers(suite.nurse_id)
        validate_error(
            api.start_adverse_event_review(event["id"], nurse_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.close_adverse_event(
                event["id"],
                make_close_review_payload(ReviewOutcome.RESUME_SAME_DRUG),
                nurse_headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

    def test_the_split_is_symmetric_and_governance_cannot_report_at_the_bedside(self, api):
        """The director owns the disposition and nothing else: the bedside record stays the
        nurse's, and the two refused nurse calls left the record untouched for the director
        to advance twice.

        Design: Corner/rbac/the_reporting_nurse_cannot_review_or_close_her_own_reaction
        """
        suite, appointment, event = self._severe_reaction(api)

        validate_error(
            api.create_adverse_event(
                appointment["id"],
                make_adverse_event_payload(1, "HOLD"),
                MEDICAL_DIRECTOR,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        rows, meta = validate_paginated(
            api.list_adverse_events(
                MEDICAL_DIRECTOR, {"appointment_id": appointment["id"]}
            )
        )
        assert meta["total_count"] == 1

        opened = validate_success(
            api.start_adverse_event_review(event["id"], MEDICAL_DIRECTOR)
        )
        assert opened["status"] == AdverseEventStatus.UNDER_REVIEW

        closed = validate_success(
            api.close_adverse_event(
                event["id"],
                make_close_review_payload(
                    ReviewOutcome.RESUME_SAME_DRUG,
                    note="Rechallenge with premedication next cycle.",
                ),
                MEDICAL_DIRECTOR,
            )
        )
        assert closed["status"] == AdverseEventStatus.CLOSED
        assert closed["version"] == 3

        cleared = read_appointment(api, appointment["id"])
        assert cleared["readiness_status"] == ReadinessStatus.FULLY_CLEARED
        assert cleared["observation_extension_minutes"] == 60

    def test_only_the_assigned_nurse_advances_the_chair_side_machine(self, api):
        """Having disposed of the reaction, the director still cannot end the administration
        leg — that remains the assigned nurse's call.

        Design: Corner/rbac/the_reporting_nurse_cannot_review_or_close_her_own_reaction
        """
        suite, appointment, event = self._severe_reaction(api)
        validate_success(api.start_adverse_event_review(event["id"], MEDICAL_DIRECTOR))
        validate_success(
            api.close_adverse_event(
                event["id"],
                make_close_review_payload(ReviewOutcome.RESUME_SAME_DRUG),
                MEDICAL_DIRECTOR,
            )
        )

        validate_error(
            api.complete_infusion(appointment["id"], MEDICAL_DIRECTOR),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        observing = validate_success(
            api.complete_infusion(
                appointment["id"], make_nurse_headers(suite.nurse_id)
            )
        )
        assert observing["schedule_status"] == ScheduleStatus.OBSERVING
