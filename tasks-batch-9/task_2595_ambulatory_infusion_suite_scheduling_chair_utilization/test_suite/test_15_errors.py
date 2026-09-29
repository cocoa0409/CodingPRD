"""One identifier per condition, observed in isolation: the per-collection catalogue of
missing rows, the header check that runs ahead of every lookup, and the pairs of rules
that fire together so that only the reported identifier tells them apart."""

from test_helpers import (
    AUTH_SPECIALIST,
    MEDICAL_DIRECTOR,
    PHARMACIST,
    SCHEDULER,
    TEST_USERS,
    AdverseEventStatus,
    ApiErrorId,
    AuthStatus,
    BookingClass,
    LabResultStatus,
    LotStatus,
    PlanStatus,
    PreparationStatus,
    ReadinessStatus,
    ReviewOutcome,
    Role,
    ScheduleStatus,
    TemplateStatus,
    assert_instant_equals,
    book_appointment,
    build_user_headers,
    check_in_visit,
    close_review,
    complete_infusion,
    compound_dose,
    confirm_visit,
    create_center,
    create_chair,
    create_drug,
    create_lot,
    create_nurse,
    create_patient,
    create_plan,
    create_template,
    discharge_visit,
    file_lab_result,
    make_appointment_payload,
    make_close_review_payload,
    make_lot_adjustment_payload,
    make_nurse_headers,
    make_plan_revision_payload,
    make_resume_payload,
    open_review,
    read_adverse_event,
    read_appointment,
    read_authorization,
    read_center,
    read_chair,
    read_lot,
    read_nurse,
    read_plan,
    read_preparation,
    read_template,
    record_reaction,
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

MISSING_ID = "99999999-9999-4999-8999-999999999999"
SETUP_CLOCK = "2026-08-01T00:00:00Z"
SERVICE_DATE = "2026-08-10"


class TestEveryCollectionNamesItsOwnMissingRow:
    """The same unknown id against ten collections, answered ten different ways."""

    def _lookups(self, api):
        return {
            "chair": api.get_chair(MISSING_ID, SCHEDULER),
            "nurse": api.get_nurse(MISSING_ID, SCHEDULER),
            "plan": api.get_treatment_plan(MISSING_ID, SCHEDULER),
            "template": api.get_template(MISSING_ID, SCHEDULER),
            "appointment": api.get_appointment(MISSING_ID, SCHEDULER),
            "authorization": api.get_authorization_request(MISSING_ID, AUTH_SPECIALIST),
            "preparation": api.get_drug_preparation(MISSING_ID, PHARMACIST),
            "event": api.get_adverse_event(MISSING_ID, MEDICAL_DIRECTOR),
            "lab": api.get_lab_result(MISSING_ID, PHARMACIST),
            "reminder": api.get_reminder_contact(MISSING_ID, SCHEDULER),
        }

    def test_the_addressed_path_chooses_the_identifier(self, api):
        """Nothing exists in the database at all, so the only thing that can select the
        identifier is the collection the caller addressed.

        Design: Corner/errors/every_addressed_collection_reports_its_own_not_found_error_id
        """
        answers = self._lookups(api)

        validate_error(answers["chair"], ApiErrorId.ERR_CHAIR_NOT_FOUND, 404)
        validate_error(answers["nurse"], ApiErrorId.ERR_NURSE_NOT_FOUND, 404)
        validate_error(answers["plan"], ApiErrorId.ERR_PLAN_NOT_FOUND, 404)
        validate_error(answers["template"], ApiErrorId.ERR_TEMPLATE_NOT_FOUND, 404)
        validate_error(answers["appointment"], ApiErrorId.ERR_APPOINTMENT_NOT_FOUND, 404)
        validate_error(
            answers["authorization"], ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND, 404
        )
        validate_error(answers["preparation"], ApiErrorId.ERR_PREPARATION_NOT_FOUND, 404)
        validate_error(answers["event"], ApiErrorId.ERR_ADVERSE_EVENT_NOT_FOUND, 404)
        validate_error(answers["lab"], ApiErrorId.ERR_LAB_RESULT_NOT_FOUND, 404)
        validate_error(answers["reminder"], ApiErrorId.ERR_REMINDER_NOT_FOUND, 404)

    def test_no_two_collections_fall_back_on_a_shared_code(self, api):
        """Ten distinct identifiers come back from ten calls, so there is no single generic
        missing-row code hiding behind the catalogue.

        Design: Corner/errors/every_addressed_collection_reports_its_own_not_found_error_id
        """
        answers = self._lookups(api)

        reported = []
        for response in answers.values():
            assert response.status_code == 404
            body = response.json()["data"]
            assert isinstance(body["message"], str)
            assert body["message"].strip() != ""
            reported.append(body["error_id"])

        assert len(set(reported)) == 10


class TestTheHeaderCheckRunsAheadOfEveryLookup:
    """Authentication is decided before the path is resolved and before the body is
    validated, so a request that is wrong in three ways still answers 401."""

    def test_a_request_with_no_role_header_is_unauthenticated_not_missing(self, api):
        """The addressed visit does not exist, yet the answer is still the authentication
        refusal rather than the missing-row one.

        Design: Corner/errors/a_missing_or_undeclared_role_header_is_unauthenticated_before_any_row_lookup
        """
        response = api.get_appointment(MISSING_ID, {"Content-Type": "application/json"})

        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert error["error_id"] != ApiErrorId.ERR_APPOINTMENT_NOT_FOUND

    def test_a_role_outside_the_declared_six_fails_authentication_not_authorization(
        self, api
    ):
        """A role name the specification never declares is not an unauthorized actor — it is
        an unauthenticated one, and the write it carried is not performed.

        Design: Corner/errors/a_missing_or_undeclared_role_header_is_unauthenticated_before_any_row_lookup
        """
        response = api.create_patient(
            {"mrn": "MRN-0001", "full_name": "Pat One", "weight_kg": 70},
            build_user_headers(TEST_USERS[Role.SCHEDULER], "Radiologist"),
        )

        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED

        rows, meta = validate_paginated(api.list_patients(SCHEDULER, {}))
        assert meta["total_count"] == 0
        assert rows == []


class TestTheRetiredTemplateOutranksItsOwnStalePinnedVersion:
    """Two 409s from the same endpoint, separated only by which of them the ladder reports
    first."""

    def _template_and_first_visit(self, api):
        suite = setup_suite(
            api,
            clock=SETUP_CLOCK,
            nurse_specs=[{"acuity_capacity_points": 12}],
        )
        first = validate_success(
            api.create_appointment(
                make_appointment_payload(
                    suite.center_id,
                    suite.patient_id,
                    suite.plan_id,
                    suite.template_id,
                    service_date=SERVICE_DATE,
                    requested_start_minute=540,
                    cycle_number=1,
                ),
                SCHEDULER,
            ),
            201,
        )
        assert first["template_version_pinned"] == 1
        return suite, first

    def test_a_resnapshot_bumps_the_version_without_retiring_the_template(self, api):
        """Re-reading the product profile advances the version, which is what makes an
        older pinned version stale while the template itself stays in service.

        Design: Corner/errors/a_retired_template_is_rejected_ahead_of_its_own_stale_pinned_version
        """
        suite, first = self._template_and_first_visit(api)

        resnapshotted = validate_success(
            api.update_template(suite.template_id, {"resnapshot": True}, PHARMACIST)
        )
        assert resnapshotted["version"] == 2
        assert resnapshotted["status"] == TemplateStatus.ACTIVE

        stale = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-17",
                requested_start_minute=540,
                cycle_number=2,
                template_version=1,
            ),
            SCHEDULER,
        )
        validate_error(stale, ApiErrorId.ERR_TEMPLATE_VERSION_STALE, 409)

        assert read_appointment(api, first["id"])["template_version_pinned"] == 1

    def test_the_current_version_still_books_and_pins_itself(self, api):
        """Neither rule is a blanket veto: asserting the version the template actually
        carries is accepted and pinned onto the new visit.

        Design: Corner/errors/a_retired_template_is_rejected_ahead_of_its_own_stale_pinned_version
        """
        suite, first = self._template_and_first_visit(api)

        validate_success(
            api.update_template(suite.template_id, {"resnapshot": True}, PHARMACIST)
        )

        second = validate_success(
            api.create_appointment(
                make_appointment_payload(
                    suite.center_id,
                    suite.patient_id,
                    suite.plan_id,
                    suite.template_id,
                    service_date="2026-08-17",
                    requested_start_minute=540,
                    cycle_number=2,
                    template_version=2,
                ),
                SCHEDULER,
            ),
            201,
        )
        assert second["template_version_pinned"] == 2

        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"template_id": suite.template_id})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 6

    def test_the_retirement_is_reported_even_though_the_pinned_version_is_stale_too(
        self, api
    ):
        """The retired template is a state precondition on the addressed row, and the
        ladder settles those before it ever compares the asserted version.

        Design: Corner/errors/a_retired_template_is_rejected_ahead_of_its_own_stale_pinned_version
        """
        suite, first = self._template_and_first_visit(api)

        validate_success(
            api.update_template(suite.template_id, {"resnapshot": True}, PHARMACIST)
        )
        retired = validate_success(
            api.update_template(
                suite.template_id, {"status": TemplateStatus.RETIRED}, SCHEDULER
            )
        )
        assert retired["version"] == 3
        assert retired["status"] == TemplateStatus.RETIRED

        response = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-24",
                requested_start_minute=540,
                cycle_number=3,
                template_version=1,
            ),
            SCHEDULER,
        )
        error = validate_error(response, ApiErrorId.ERR_TEMPLATE_RETIRED, 409)
        assert error["error_id"] != ApiErrorId.ERR_TEMPLATE_VERSION_STALE

        assert read_template(api, suite.template_id)["status"] == TemplateStatus.RETIRED


class TestTheAdjustmentIsJudgedOnItsResultAndNotOnItsSize:
    """A signed correction against a five-unit lot, refused at minus six and accepted at
    minus five."""

    def _small_lot(self, api):
        set_clock(api, SETUP_CLOCK)
        drug = create_drug(api)
        lot = create_lot(api, drug["id"], units_received=5)
        assert lot["units_available"] == 5
        assert lot["version"] == 1
        return drug, lot

    def test_the_refused_correction_leaves_the_ledger_and_the_version_alone(self, api):
        """A correction that would land the available count at minus one is refused, and
        because nothing was written the next attempt reuses the same expected version.

        Design: Corner/errors/an_adjustment_that_would_drive_units_available_below_zero_is_rejected
        """
        drug, lot = self._small_lot(api)

        response = api.create_lot_adjustment(
            lot["id"],
            make_lot_adjustment_payload(-6, 1, reason="Physical count shrinkage"),
            PHARMACIST,
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_DRUG_UNITS, 422)

        unchanged = read_lot(api, lot["id"])
        assert unchanged["units_received"] == 5
        assert unchanged["units_available"] == 5
        assert unchanged["version"] == 1
        assert unchanged["status"] == LotStatus.AVAILABLE

    def test_landing_exactly_on_zero_depletes_the_lot(self, api):
        """Zero is inside the permitted range, so the correction that empties the lot is
        accepted and the lot derives DEPLETED from the recomputation.

        The follow-on "a credit revives it" leg is deliberately not asserted: the PRD's
        adjustment rule says an adjustment "against a lot that is no longer AVAILABLE --
        because it has expired or been depleted -- is refused with ERR_LOT_NOT_AVAILABLE
        (HTTP 409)", which contradicts the DEPLETED-to-AVAILABLE aside that lists a positive
        adjustment among the reviving recomputations, so the outcome of that second call is
        not uniquely determined by the contract.

        Design: Corner/errors/an_adjustment_that_would_drive_units_available_below_zero_is_rejected
        """
        drug, lot = self._small_lot(api)

        emptied = validate_success(
            api.create_lot_adjustment(
                lot["id"],
                make_lot_adjustment_payload(-5, 1, reason="Physical count shrinkage"),
                PHARMACIST,
            )
        )
        assert emptied["units_available"] == 0
        assert emptied["status"] == LotStatus.DEPLETED
        assert emptied["version"] == 2
        assert emptied["units_received"] == 0
        assert emptied["units_committed"] == 0
        assert emptied["units_administered"] == 0
        assert emptied["units_wasted"] == 0


class TestThePastDateBarComparesCalendarDatesOnly:
    """A clock sitting at midday, a yesterday that is refused and a tomorrow whose morning
    minute has already elapsed today."""

    def _midday_suite(self, api):
        return setup_suite(api, clock="2026-08-10T12:00:00Z")

    def test_yesterday_is_refused(self, api):
        """A service date before the clock's own date is out of reach whatever minute it
        names.

        Design: Corner/errors/a_service_date_earlier_than_the_clocks_date_is_rejected
        """
        suite = self._midday_suite(api)

        response = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-09",
                requested_start_minute=540,
                cycle_number=1,
            ),
            SCHEDULER,
        )
        validate_error(response, ApiErrorId.ERR_SERVICE_DATE_IN_PAST, 422)

        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": suite.patient_id})
        )
        assert meta["total_count"] == 0

    def test_tomorrow_morning_is_accepted_although_that_minute_has_passed_today(self, api):
        """The rule compares dates and not instants, so a start minute that is already
        behind the clock today is perfectly bookable tomorrow.

        Design: Corner/errors/a_service_date_earlier_than_the_clocks_date_is_rejected
        """
        suite = self._midday_suite(api)

        booked = validate_success(
            api.create_appointment(
                make_appointment_payload(
                    suite.center_id,
                    suite.patient_id,
                    suite.plan_id,
                    suite.template_id,
                    service_date="2026-08-11",
                    requested_start_minute=540,
                    cycle_number=1,
                ),
                SCHEDULER,
            ),
            201,
        )
        assert booked["service_date"] == "2026-08-11"
        assert booked["start_minute"] == 540

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": suite.patient_id})
        )
        assert meta["total_count"] == 1


class TestTheSupersededRegimenIsClosedOnAllThreeWriteSurfaces:
    """One dose revision, and the old regimen refuses booking, resumption and a second
    revision while its successor books normally."""

    def _revised_regimen(self, api):
        suite = setup_suite(
            api,
            clock=SETUP_CLOCK,
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
        successor = validate_success(
            api.create_plan_revision(
                suite.plan_id,
                make_plan_revision_payload(
                    1, dose_mg_per_kg=12, total_cycles=6, premed_waived=False
                ),
                MEDICAL_DIRECTOR,
            ),
            201,
        )
        return suite, first, successor

    def test_the_revision_closes_the_old_regimen_and_frees_its_visit(self, api):
        """The superseded regimen keeps its history but loses its live visit, which is
        cancelled without charge and gives its chair and nurse back.

        Design: Corner/errors/a_superseded_regimen_refuses_bookings_resumes_and_further_revisions
        """
        suite, first, successor = self._revised_regimen(api)

        assert successor["status"] == PlanStatus.ACTIVE
        assert successor["supersedes_plan_id"] == suite.plan_id

        superseded = read_plan(api, suite.plan_id)
        assert superseded["status"] == PlanStatus.SUPERSEDED
        assert superseded["version"] == 2

        released = read_appointment(api, first["id"])
        assert released["schedule_status"] == ScheduleStatus.CANCELLED
        assert released["cancellation_charge_cents"] == 0
        # The revision cascade "cancels" the live visit, and a cancellation's chair_id and
        # nurse_id are "deliberately not cleared -- they remain as an audit trail of who was
        # scheduled to do the work"; what the cascade releases is the chair minutes and the
        # nurse acuity, because CANCELLED sits outside the committed set.
        assert released["chair_id"] == first["chair_id"]
        assert released["nurse_id"] == first["nurse_id"]
        assert read_chair(api, first["chair_id"])["committed_minutes"] == 0

    def test_booking_resuming_and_revising_all_report_the_superseded_regimen(self, api):
        """Three different write surfaces, one identifier — and the second revision supplies
        the row's current version, so it is the state check firing rather than the
        concurrency guard.

        Design: Corner/errors/a_superseded_regimen_refuses_bookings_resumes_and_further_revisions
        """
        suite, first, successor = self._revised_regimen(api)

        booking = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-17",
                requested_start_minute=540,
                cycle_number=2,
            ),
            SCHEDULER,
        )
        validate_error(booking, ApiErrorId.ERR_PLAN_SUPERSEDED, 409)

        resumption = api.resume_treatment_plan(
            suite.plan_id,
            make_resume_payload("Attempt to revive the old dose"),
            MEDICAL_DIRECTOR,
        )
        validate_error(resumption, ApiErrorId.ERR_PLAN_SUPERSEDED, 409)

        current_version = read_plan(api, suite.plan_id)["version"]
        assert current_version == 2

        second_revision = api.create_plan_revision(
            suite.plan_id,
            make_plan_revision_payload(
                current_version, dose_mg_per_kg=14, total_cycles=6, premed_waived=False
            ),
            MEDICAL_DIRECTOR,
        )
        error = validate_error(second_revision, ApiErrorId.ERR_PLAN_SUPERSEDED, 409)
        assert error["error_id"] != ApiErrorId.ERR_STALE_PLAN_VERSION

    def test_the_successor_regimen_books_onto_the_chair_the_cancellation_freed(self, api):
        """The refusals are about the old row alone: the replacement regimen books at the
        same minute on the same chair, at a dose that is still inside the tier the
        template declares.

        Design: Corner/errors/a_superseded_regimen_refuses_bookings_resumes_and_further_revisions
        """
        suite, first, successor = self._revised_regimen(api)

        replacement = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            successor["id"],
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )
        assert replacement["chair_id"] == suite.chair_id("A1")
        assert replacement["chair_minutes"] == 240

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3


class TestTheCompletedRegimenRefusesTheRepeatOfItsOnlyCycle:
    """A single-cycle regimen that closes itself at discharge, and the repeat booking that
    reports the closed regimen rather than the exhausted cycle."""

    def _finished_regimen(self, api):
        suite, appointment = setup_confirmed_visit(
            api,
            clock="2026-08-10T08:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            lab_collected_at="2026-08-10T07:00:00Z",
            plan_overrides={"total_cycles": 1},
        )
        lot = create_lot(api, suite.drug_id, units_received=10)
        check_in_visit(api, appointment["id"])

        set_clock(api, "2026-08-10T08:30:00Z")
        requested = request_dose(api, appointment["id"], units_requested=1)
        prep = compound_dose(api, requested["id"])

        set_clock(api, "2026-08-10T09:00:00Z")
        start_infusion(api, appointment["id"], suite.nurse_id)
        set_clock(api, "2026-08-10T11:30:00Z")
        complete_infusion(api, appointment["id"], suite.nurse_id)
        set_clock(api, "2026-08-10T13:15:00Z")
        completed = discharge_visit(api, appointment["id"], suite.nurse_id)
        return suite, completed, prep, lot

    def test_the_last_cycle_closes_the_regimen_and_settles_the_ledger(self, api):
        """Discharge bubbles the cycle counters up, and with the only cycle done the regimen
        closes itself while the dose is charged out of the lot.

        Design: Corner/errors/a_completed_regimen_refuses_the_repeat_booking_and_the_resume
        """
        suite, completed, prep, lot = self._finished_regimen(api)

        assert completed["schedule_status"] == ScheduleStatus.COMPLETED
        assert completed["billable_chair_units"] == 17

        finished = read_plan(api, suite.plan_id)
        assert finished["status"] == PlanStatus.COMPLETED
        assert finished["completed_cycles"] == 1
        assert finished["first_dose_completed"] is True

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_preparation(api, prep["id"])["status"] == PreparationStatus.ADMINISTERED

        settled = read_lot(api, lot["id"])
        assert settled["units_administered"] == 1
        assert settled["units_available"] == 9

    def test_the_repeat_booking_resume_and_revision_all_report_the_closed_regimen(
        self, api
    ):
        """Cycle 1 is both already held and out of a closed regimen's reach, and the closed
        regimen is what the refusal names.

        Design: Corner/errors/a_completed_regimen_refuses_the_repeat_booking_and_the_resume
        """
        suite, completed, prep, lot = self._finished_regimen(api)

        repeat = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date="2026-08-17",
                requested_start_minute=540,
                cycle_number=1,
            ),
            SCHEDULER,
        )
        error = validate_error(repeat, ApiErrorId.ERR_PLAN_COMPLETED, 409)
        assert error["error_id"] != ApiErrorId.ERR_CYCLE_OUT_OF_RANGE

        resumption = api.resume_treatment_plan(
            suite.plan_id,
            make_resume_payload("Add another cycle after the fact"),
            MEDICAL_DIRECTOR,
        )
        validate_error(resumption, ApiErrorId.ERR_PLAN_COMPLETED, 409)

        current_version = read_plan(api, suite.plan_id)["version"]
        revision = api.create_plan_revision(
            suite.plan_id,
            make_plan_revision_payload(
                current_version, dose_mg_per_kg=12, total_cycles=4, premed_waived=False
            ),
            MEDICAL_DIRECTOR,
        )
        validate_error(revision, ApiErrorId.ERR_PLAN_COMPLETED, 409)

        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"treatment_plan_id": suite.plan_id})
        )
        assert meta["total_count"] == 1


class TestTheLapsedApprovalIsJudgedOnItsInstantAndThenOnItsStatus:
    """The same check-in call, refused twice for two different reasons, separated only by
    whether the ops checkpoint has yet noticed the expiry."""

    def _lapsed_authorization(self, api):
        suite = setup_suite(api, clock=SETUP_CLOCK)
        appointment = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-09-15",
            requested_start_minute=540,
            cycle_number=1,
        )
        auth = setup_approved_authorization(api, appointment["id"])
        confirmed = confirm_visit(api, appointment["id"])
        set_clock(api, "2026-09-15T08:00:00Z")
        return suite, appointment, auth, confirmed

    def test_the_expiry_instant_bars_the_seat_while_the_row_still_reads_approved(
        self, api
    ):
        """Coverage granted on the first of August lapses thirty days later, and the
        check-in compares that instant against the clock rather than trusting the stored
        status — which is still the one that cleared the confirmation.

        Design: Corner/errors/check_in_after_the_authorization_expiry_instant_is_rejected
        """
        suite, appointment, auth, confirmed = self._lapsed_authorization(api)

        assert_instant_equals(auth["expires_at"], "2026-08-31T00:00:00Z")
        assert auth["status"] == AuthStatus.APPROVED
        assert confirmed["schedule_status"] == ScheduleStatus.CONFIRMED

        response = api.check_in_appointment(appointment["id"], SCHEDULER)
        validate_error(response, ApiErrorId.ERR_AUTH_EXPIRED, 409)

        assert read_authorization(api, auth["id"])["status"] == AuthStatus.APPROVED
        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240

    def test_once_the_checkpoint_files_the_expiry_the_refusal_changes_its_name(self, api):
        """The ops checkpoint moves the lapsed approval out of `APPROVED`, and with no
        approval left standing the earlier rule in the ladder claims the identical call.

        Design: Corner/errors/check_in_after_the_authorization_expiry_instant_is_rejected
        """
        suite, appointment, auth, confirmed = self._lapsed_authorization(api)

        swept = run_sweep(api, suite.center_id, "2026-09-15")
        assert swept["expired_authorization_count"] == 1
        assert swept["no_show_count"] == 0

        assert read_authorization(api, auth["id"])["status"] == AuthStatus.EXPIRED

        response = api.check_in_appointment(appointment["id"], SCHEDULER)
        error = validate_error(response, ApiErrorId.ERR_AUTH_NOT_APPROVED, 409)
        assert error["error_id"] != ApiErrorId.ERR_AUTH_EXPIRED

        still_waiting = read_appointment(api, appointment["id"])
        assert still_waiting["schedule_status"] == ScheduleStatus.CONFIRMED
        assert still_waiting["readiness_status"] == ReadinessStatus.PENDING


class TestTheUrgentQuotaIsConsultedBeforeTheChairSearch:
    """One reserved chair, one routine visit already sitting on it, and the two urgent
    refusals told apart by which quantity has actually run out."""

    def _center_with_one_late_reserved_chair(self, api):
        set_clock(api, SETUP_CLOCK)
        center = create_center(api, urgent_reserve_chair_count=1)
        chair = create_chair(api, center["id"], "A2", reserved_for_urgent=False)
        nurse = create_nurse(api, center["id"], acuity_capacity_points=12)
        drug = create_drug(api)
        template = create_template(api, center["id"], drug["id"])

        people = {}
        for key, mrn, name in (
            ("routine", "MRN-R001", "Rhoda Routine"),
            ("urgent_one", "MRN-U001", "Ursula One"),
            ("urgent_two", "MRN-U002", "Ulric Two"),
        ):
            patient = create_patient(api, mrn=mrn, full_name=name)
            plan = create_plan(api, patient["id"], drug["id"])
            people[key] = (patient["id"], plan["id"])

        routine_patient, routine_plan = people["routine"]
        routine = book_appointment(
            api,
            center["id"],
            routine_patient,
            routine_plan,
            template["id"],
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )
        validate_success(
            api.update_chair(chair["id"], {"reserved_for_urgent": True}, SCHEDULER)
        )
        set_clock(api, "2026-08-10T08:00:00Z")
        return center["id"], chair["id"], nurse["id"], template["id"], people, routine

    def _urgent_request(self, api, center_id, template_id, who, start_minute):
        patient_id, plan_id = who
        return api.create_appointment(
            make_appointment_payload(
                center_id,
                patient_id,
                plan_id,
                template_id,
                service_date=SERVICE_DATE,
                requested_start_minute=start_minute,
                cycle_number=1,
                booking_class=BookingClass.URGENT,
            ),
            SCHEDULER,
        )

    def test_an_unclaimed_reserve_lets_the_quota_pass_and_the_occupied_minute_refuse(
        self, api
    ):
        """Flagging a chair as the reserve does not evict the routine visit already holding
        it, so the single urgent candidate minute has no chair free even though the reserve
        itself is untouched.

        Design: Corner/errors/the_urgent_reserve_limit_outranks_the_unavailable_chair_at_the_same_center
        """
        center_id, chair_id, nurse_id, template_id, people, routine = (
            self._center_with_one_late_reserved_chair(api)
        )

        held = read_chair(api, chair_id)
        assert held["reserved_for_urgent"] is True
        centre = read_center(api, center_id)
        assert centre["reserved_chair_count"] == 1
        assert centre["available_chair_count"] == 1

        kept = read_appointment(api, routine["id"])
        assert kept["chair_id"] == chair_id
        assert kept["schedule_status"] == ScheduleStatus.TENTATIVE

        response = self._urgent_request(
            api, center_id, template_id, people["urgent_one"], 540
        )
        validate_error(response, ApiErrorId.ERR_URGENT_RESERVE_UNAVAILABLE, 409)

    def test_the_urgent_visit_claims_the_reserved_chair_at_a_minute_that_is_free(
        self, api
    ):
        """A start clear of the routine occupancy and its turnover buffer, whose own window
        still closes inside the service day, seats the urgent patient on the reserve.

        Design: Corner/errors/the_urgent_reserve_limit_outranks_the_unavailable_chair_at_the_same_center
        """
        center_id, chair_id, nurse_id, template_id, people, routine = (
            self._center_with_one_late_reserved_chair(api)
        )

        seated = validate_success(
            self._urgent_request(api, center_id, template_id, people["urgent_one"], 810),
            201,
        )
        assert seated["start_minute"] == 810
        assert seated["chair_id"] == chair_id
        assert seated["end_minute"] == 1050

    def test_the_claimed_reserve_reports_the_quota_rather_than_the_collision(self, api):
        """With the one reserved chair now claimed by an urgent visit, the next urgent
        request is refused on the quota — and the minute it asks for is occupied too, so
        only the reported identifier shows which rule was consulted first.

        Design: Corner/errors/the_urgent_reserve_limit_outranks_the_unavailable_chair_at_the_same_center
        """
        center_id, chair_id, nurse_id, template_id, people, routine = (
            self._center_with_one_late_reserved_chair(api)
        )
        validate_success(
            self._urgent_request(api, center_id, template_id, people["urgent_one"], 810),
            201,
        )

        response = self._urgent_request(
            api, center_id, template_id, people["urgent_two"], 480
        )
        error = validate_error(response, ApiErrorId.ERR_URGENT_RESERVE_LIMIT, 409)
        assert error["error_id"] != ApiErrorId.ERR_URGENT_RESERVE_UNAVAILABLE

        assert read_chair(api, chair_id)["committed_minutes"] == 480
        assert read_nurse(api, nurse_id)["assigned_acuity_points"] == 6

        rows, meta = validate_paginated(
            api.list_appointments(
                SCHEDULER, {"center_id": center_id, "booking_class": BookingClass.URGENT}
            )
        )
        assert meta["total_count"] == 1


class TestOneReviewIdentifierGuardsBothEdgesOfTheReactionRecord:
    """A close before the open, a repeated open, and both calls against the terminal state —
    four refusals, one identifier, and no version movement on any of them."""

    def _severe_reaction(self, api):
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
        requested = request_dose(api, appointment["id"], units_requested=2)
        compound_dose(api, requested["id"])

        set_clock(api, "2026-08-10T09:00:00Z")
        start_infusion(api, appointment["id"], suite.nurse_id)
        event = record_reaction(
            api, appointment["id"], suite.nurse_id, grade=3, action="HOLD"
        )
        return suite, appointment, event

    def test_the_close_is_refused_before_the_review_is_ever_opened(self, api):
        """A freshly reported reaction has not been reviewed by anyone, so the disposition
        cannot be recorded yet — and the refusal leaves the record exactly as it was.

        Design: Corner/errors/the_reaction_review_refuses_a_close_before_the_open_and_every_repeat_call
        """
        suite, appointment, event = self._severe_reaction(api)

        assert event["observation_extension_minutes"] == 60
        assert event["reported_by_nurse_id"] == suite.nurse_id
        assert event["status"] == AdverseEventStatus.REPORTED
        assert event["version"] == 1

        response = api.close_adverse_event(
            event["id"],
            make_close_review_payload(
                ReviewOutcome.RESUME_SAME_DRUG, note="Premature close attempt"
            ),
            MEDICAL_DIRECTOR,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ADVERSE_EVENT_STATE, 409)

        untouched = read_adverse_event(api, event["id"])
        assert untouched["status"] == AdverseEventStatus.REPORTED
        assert untouched["version"] == 1

    def test_neither_the_open_nor_the_close_may_be_repeated(self, api):
        """The two accepted calls each advance the record once; the three refused ones —
        the repeat open, the repeat close and the open against a closed record — advance
        nothing and do not overwrite the disposition already stored.

        Design: Corner/errors/the_reaction_review_refuses_a_close_before_the_open_and_every_repeat_call
        """
        suite, appointment, event = self._severe_reaction(api)

        opened = open_review(api, event["id"])
        assert opened["status"] == AdverseEventStatus.UNDER_REVIEW
        assert opened["version"] == 2

        repeat_open = api.start_adverse_event_review(event["id"], MEDICAL_DIRECTOR)
        validate_error(repeat_open, ApiErrorId.ERR_INVALID_ADVERSE_EVENT_STATE, 409)

        closed = close_review(api, event["id"], ReviewOutcome.RESUME_SAME_DRUG)
        assert closed["status"] == AdverseEventStatus.CLOSED
        assert closed["review_outcome"] == ReviewOutcome.RESUME_SAME_DRUG
        assert closed["version"] == 3

        repeat_close = api.close_adverse_event(
            event["id"],
            make_close_review_payload(ReviewOutcome.DISCONTINUE),
            MEDICAL_DIRECTOR,
        )
        validate_error(repeat_close, ApiErrorId.ERR_INVALID_ADVERSE_EVENT_STATE, 409)

        reopen = api.start_adverse_event_review(event["id"], MEDICAL_DIRECTOR)
        validate_error(reopen, ApiErrorId.ERR_INVALID_ADVERSE_EVENT_STATE, 409)

        settled = read_adverse_event(api, event["id"])
        assert settled["version"] == 3
        assert settled["review_outcome"] == ReviewOutcome.RESUME_SAME_DRUG

    def test_the_observation_extension_outlives_the_review_it_came_from(self, api):
        """Clearing the patient to resume the same product lifts the clinical block, but the
        extra hour of watching the reaction earned is not given back.

        Design: Corner/errors/the_reaction_review_refuses_a_close_before_the_open_and_every_repeat_call
        """
        suite, appointment, event = self._severe_reaction(api)

        open_review(api, event["id"])
        close_review(api, event["id"], ReviewOutcome.RESUME_SAME_DRUG)

        watched = read_appointment(api, appointment["id"])
        assert watched["observation_extension_minutes"] == 60
        assert watched["observation_minutes"] == 120
        assert watched["chair_minutes"] == 300
        assert watched["end_minute"] == 840
        assert watched["readiness_status"] == ReadinessStatus.FULLY_CLEARED
        assert watched["schedule_status"] == ScheduleStatus.INFUSING

        assert read_plan(api, suite.plan_id)["status"] == PlanStatus.ACTIVE


class TestTheStartGateReportsItsTwoGapsOneAtATime:
    """Two independent gaps open on the same call, closed one at a time so that each
    refusal is observed by itself."""

    def _visit_with_no_lab_and_an_unmixed_dose(self, api):
        suite, appointment = setup_confirmed_visit(
            api,
            clock="2026-08-10T08:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            with_lab=False,
        )
        lot = create_lot(api, suite.drug_id, units_received=10)

        set_clock(api, "2026-08-10T08:30:00Z")
        requested = request_dose(api, appointment["id"], units_requested=1)
        checked_in = check_in_visit(api, appointment["id"])

        set_clock(api, "2026-08-10T09:00:00Z")
        return suite, appointment, requested, checked_in, lot

    def test_the_absent_draw_is_reported_ahead_of_the_unmixed_dose(self, api):
        """No draw exists for this patient at all and the dose is still only requested, yet
        the laboratory gap is the one the caller is told about.

        Design: Corner/errors/the_start_infusion_gate_reports_the_missing_lab_ahead_of_the_uncompounded_dose
        """
        suite, appointment, requested, checked_in, lot = (
            self._visit_with_no_lab_and_an_unmixed_dose(api)
        )

        assert requested["status"] == PreparationStatus.REQUESTED
        assert checked_in["schedule_status"] == ScheduleStatus.CHECKED_IN
        assert checked_in["readiness_status"] == ReadinessStatus.AUTH_CLEARED

        response = api.start_infusion(
            appointment["id"], make_nurse_headers(suite.nurse_id)
        )
        validate_error(response, ApiErrorId.ERR_LAB_RESULT_MISSING, 422)

    def test_filing_the_draw_moves_the_identical_call_onto_the_second_gap(self, api):
        """A draw carrying both values is filed and passes the gate, so the very same call
        now fails only on the dose that was never mixed.

        Design: Corner/errors/the_start_infusion_gate_reports_the_missing_lab_ahead_of_the_uncompounded_dose
        """
        suite, appointment, requested, checked_in, lot = (
            self._visit_with_no_lab_and_an_unmixed_dose(api)
        )

        drawn = file_lab_result(
            api,
            suite.patient_id,
            collected_at="2026-08-10T06:00:00Z",
            anc_value=2.0,
            platelet_value=150,
            headers=make_nurse_headers(suite.nurse_id),
        )
        assert drawn["status"] == LabResultStatus.RESULTED

        response = api.start_infusion(
            appointment["id"], make_nurse_headers(suite.nurse_id)
        )
        error = validate_error(response, ApiErrorId.ERR_PREPARATION_NOT_READY, 409)
        assert error["error_id"] != ApiErrorId.ERR_LAB_RESULT_MISSING

    def test_mixing_the_dose_closes_the_last_gap_and_the_call_goes_through(self, api):
        """With the draw on file and the dose standing by, the infusion starts — and the
        mixing itself moved no lot counters.

        Design: Corner/errors/the_start_infusion_gate_reports_the_missing_lab_ahead_of_the_uncompounded_dose
        """
        suite, appointment, requested, checked_in, lot = (
            self._visit_with_no_lab_and_an_unmixed_dose(api)
        )
        file_lab_result(
            api,
            suite.patient_id,
            collected_at="2026-08-10T06:00:00Z",
            anc_value=2.0,
            platelet_value=150,
            headers=make_nurse_headers(suite.nurse_id),
        )

        mixed = compound_dose(api, requested["id"])
        assert mixed["status"] == PreparationStatus.PREPARED
        assert_instant_equals(mixed["usable_until"], "2026-08-10T13:00:00Z")

        started = validate_success(
            api.start_infusion(appointment["id"], make_nurse_headers(suite.nurse_id))
        )
        assert started["schedule_status"] == ScheduleStatus.INFUSING
        assert started["actual_start_minute"] == 540
        assert started["readiness_status"] == ReadinessStatus.FULLY_CLEARED

        committed = read_lot(api, lot["id"])
        assert committed["units_committed"] == 1
        assert committed["units_available"] == 9
        assert committed["units_administered"] == 0
