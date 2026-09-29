"""Rules read at the exact instant or the exact edge where they engage, and pairs of
rules that fail together so that only the precedence ladder decides which is reported."""

from test_helpers import (
    AdverseEventStatus,
    ApiClient,
    ApiErrorId,
    BookingClass,
    DoseTier,
    PHARMACIST,
    PlanStatus,
    PreparationStatus,
    ReadinessStatus,
    ReminderCadenceCode,
    ReminderTier,
    ReviewOutcome,
    RiskVariant,
    SCHEDULER,
    ScheduleStatus,
    SteeringStatus,
    assert_instant_equals,
    assert_two_decimal_places,
    book_appointment,
    check_in_visit,
    close_review,
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
    file_lab_result,
    inject_history,
    make_appointment_payload,
    make_patient_payload,
    open_review,
    read_appointment,
    read_chair,
    read_lot,
    read_no_show_risk,
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
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2026-08-05T07:00:00Z"
SERVICE_DATE = "2026-08-10"


class TestTheMedicalRecordNumberIsUniqueOnItsOwn:
    """The key is the record number and nothing else, and the refusal writes no row."""

    def test_a_second_registration_on_the_same_number_is_refused(self, api):
        """The collection still holds exactly one row under that number afterwards, and it
        is still the original registration rather than the impostor.

        Design: Corner/validations/a_second_patient_with_the_same_mrn_is_refused_and_no_row_is_written
        """
        set_clock(api, SETUP_CLOCK)
        original = create_patient(api, mrn="MRN-0001", full_name="Pat One", weight_kg=70)

        response = api.create_patient(
            make_patient_payload("MRN-0001", "Impostor Two", weight_kg=55), SCHEDULER
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_MRN, 409)

        rows, meta = validate_paginated(
            api.list_patients(SCHEDULER, {"mrn": "MRN-0001"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == original["id"]
        assert rows[0]["full_name"] == "Pat One"
        assert rows[0]["weight_kg"] == 70

    def test_an_identical_name_and_weight_register_again_under_another_number(self, api):
        """Neither the name nor the dosing weight is part of the uniqueness key, so the same
        person's details go in again under a different number and take the declared
        defaults.

        Design: Corner/validations/a_second_patient_with_the_same_mrn_is_refused_and_no_row_is_written
        """
        set_clock(api, SETUP_CLOCK)
        original = create_patient(api, mrn="MRN-0001", full_name="Pat One", weight_kg=70)

        twin = validate_success(
            api.create_patient(
                make_patient_payload("MRN-0002", "Pat One", weight_kg=70), SCHEDULER
            ),
            201,
        )

        assert twin["id"] != original["id"]
        assert twin["no_show_strikes"] == 0
        assert_two_decimal_places(twin["no_show_risk_score"], 0.00)
        assert twin["reminder_tier"] == ReminderTier.STANDARD
        assert twin["waste_liability_cents"] == 0
        assert twin["steering_status"] == SteeringStatus.SUITE


class TestAnAddOnAtTheCutoffMinuteFillsTheDayToItsClose:
    """Two inclusive edges are satisfied by one request: the cutoff and the close."""

    def _suite_on_the_cutoff_minute(self, api: ApiClient):
        suite = setup_suite(api, clock="2026-08-01T15:00:00Z")
        return suite

    def test_arriving_exactly_at_the_cutoff_is_accepted(self, api):
        """The clock sits on minute 900, which is the centre's add-on cutoff exactly, and an
        arrival at the cutoff is declared acceptable.

        Design: Corner/validations/an_add_on_arriving_exactly_at_the_cutoff_minute_books_a_window_ending_exactly_at_close
        """
        suite = self._suite_on_the_cutoff_minute(api)

        appointment = validate_success(
            api.create_appointment(
                make_appointment_payload(
                    suite.center_id,
                    suite.patient_id,
                    suite.plan_id,
                    suite.template_id,
                    service_date="2026-08-01",
                    requested_start_minute=900,
                    cycle_number=1,
                    booking_class=BookingClass.SAME_DAY_ADDON,
                ),
                SCHEDULER,
            ),
            201,
        )

        assert appointment["start_minute"] == 900
        assert appointment["end_minute"] == 1140
        assert appointment["booking_class"] == BookingClass.SAME_DAY_ADDON
        assert appointment["schedule_status"] == ScheduleStatus.TENTATIVE
        assert appointment["readiness_status"] == ReadinessStatus.PENDING

    def test_a_window_whose_exclusive_end_lands_on_the_close_still_fits(self, api):
        """Thirty minutes of pre-medication, one hundred and fifty of administration and an
        hour of first-dose observation occupy the chair to 1140 precisely, and the fit
        test is satisfied on equality.

        Design: Corner/validations/an_add_on_arriving_exactly_at_the_cutoff_minute_books_a_window_ending_exactly_at_close
        """
        suite = self._suite_on_the_cutoff_minute(api)

        appointment = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date="2026-08-01",
            requested_start_minute=900,
            cycle_number=1,
            booking_class=BookingClass.SAME_DAY_ADDON,
        )

        assert appointment["chair_minutes"] == 240
        assert appointment["premed_minutes"] == 30
        assert appointment["admin_minutes"] == 150
        assert appointment["observation_minutes"] == 60
        assert appointment["acuity_points"] == 3
        assert appointment["chair_id"] == suite.chair_id("A1")
        assert appointment["nurse_id"] == suite.nurse_id

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3


class TestTheRegimenOwnerIsCheckedBeforeTheCycleNumber:
    """One request breaks both rules at once, and both answer with the same status code."""

    def _one_regimen_and_a_stranger(self, api: ApiClient):
        suite = setup_suite(api, clock=SETUP_CLOCK)
        stranger = create_patient(api, mrn="MRN-0002", full_name="Pat Two")
        return suite, stranger

    def test_the_owner_mismatch_is_reported_ahead_of_the_out_of_range_cycle(self, api):
        """The regimen belongs to another patient and the cycle number is far past the
        regimen's length; the coherence order names the owner mismatch first.

        Design: Corner/validations/plan_patient_mismatch_at_sixty_is_reported_ahead_of_the_out_of_range_cycle_at_sixty_five
        """
        suite, stranger = self._one_regimen_and_a_stranger(api)

        response = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                stranger["id"],
                suite.plan_id,
                suite.template_id,
                service_date=SERVICE_DATE,
                requested_start_minute=540,
                cycle_number=99,
            ),
            SCHEDULER,
        )

        body = validate_error(response, ApiErrorId.ERR_PLAN_PATIENT_MISMATCH, 422)
        assert body["error_id"] != ApiErrorId.ERR_CYCLE_OUT_OF_RANGE

    def test_repairing_only_the_owner_surfaces_the_cycle_rule(self, api):
        """The cycle rule was live all along and merely outranked, so naming the right
        patient in an otherwise identical request brings it to the surface.

        Design: Corner/validations/plan_patient_mismatch_at_sixty_is_reported_ahead_of_the_out_of_range_cycle_at_sixty_five
        """
        suite, _stranger = self._one_regimen_and_a_stranger(api)

        response = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date=SERVICE_DATE,
                requested_start_minute=540,
                cycle_number=99,
            ),
            SCHEDULER,
        )

        validate_error(response, ApiErrorId.ERR_CYCLE_OUT_OF_RANGE, 422)

    def test_the_last_cycle_of_the_regimen_is_bookable_and_only_it_took_capacity(self, api):
        """The range runs from one through the regimen's length inclusive, so the sixth cycle
        of a six-cycle regimen books; neither refusal wrote a row or consumed a chair.

        Design: Corner/validations/plan_patient_mismatch_at_sixty_is_reported_ahead_of_the_out_of_range_cycle_at_sixty_five
        """
        suite, stranger = self._one_regimen_and_a_stranger(api)
        api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                stranger["id"],
                suite.plan_id,
                suite.template_id,
                service_date=SERVICE_DATE,
                requested_start_minute=540,
                cycle_number=99,
            ),
            SCHEDULER,
        )
        api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date=SERVICE_DATE,
                requested_start_minute=540,
                cycle_number=99,
            ),
            SCHEDULER,
        )

        accepted = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=6,
        )

        assert accepted["cycle_number"] == 6

        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"treatment_plan_id": suite.plan_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]
        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240


class TestTheTemplatesDrugIsCheckedBeforeItsCentre:
    """The two referential checks read different sources and sit one step apart."""

    def _two_centres_and_a_doubly_wrong_template(self, api: ApiClient):
        set_clock(api, SETUP_CLOCK)
        home = create_center(api, name="Home Suite")
        away = create_center(api, name="Away Suite")
        home_chair = create_chair(api, home["id"], "A1")
        home_nurse = create_nurse(api, home["id"])
        create_chair(api, away["id"], "B1")
        create_nurse(api, away["id"])
        reference = create_drug(api)
        alternative = create_drug(api, name="Infliximab-Alt")
        templates = {
            "home_reference": create_template(
                api, home["id"], reference["id"], DoseTier.MID
            ),
            "away_alternative": create_template(
                api, away["id"], alternative["id"], DoseTier.MID
            ),
            "away_reference": create_template(
                api, away["id"], reference["id"], DoseTier.MID
            ),
        }
        patient = create_patient(api)
        plan = create_plan(api, patient["id"], reference["id"])
        return home, away, home_chair, home_nurse, templates, patient, plan

    def _booking_attempt(self, api, center, patient, plan, template):
        return api.create_appointment(
            make_appointment_payload(
                center["id"],
                patient["id"],
                plan["id"],
                template["id"],
                service_date=SERVICE_DATE,
                requested_start_minute=540,
                cycle_number=1,
            ),
            SCHEDULER,
        )

    def test_the_wrong_drug_is_reported_even_though_the_centre_is_wrong_too(self, api):
        """The template belongs to the other centre and to the other product; the drug check
        is compared against the regimen's product and is declared first.

        Design: Corner/validations/template_drug_mismatch_outranks_the_center_mismatch_on_one_doubly_wrong_template
        """
        home, _away, _chair, _nurse, templates, patient, plan = (
            self._two_centres_and_a_doubly_wrong_template(api)
        )

        response = self._booking_attempt(
            api, home, patient, plan, templates["away_alternative"]
        )

        body = validate_error(response, ApiErrorId.ERR_TEMPLATE_DRUG_MISMATCH, 422)
        assert body["error_id"] != ApiErrorId.ERR_TEMPLATE_CENTER_MISMATCH

    def test_a_template_of_the_right_drug_at_the_wrong_centre_names_the_centre(self, api):
        """With the product now matching, the same request shape reaches the next check in
        the coherence order.

        Design: Corner/validations/template_drug_mismatch_outranks_the_center_mismatch_on_one_doubly_wrong_template
        """
        home, _away, _chair, _nurse, templates, patient, plan = (
            self._two_centres_and_a_doubly_wrong_template(api)
        )

        response = self._booking_attempt(
            api, home, patient, plan, templates["away_reference"]
        )

        validate_error(response, ApiErrorId.ERR_TEMPLATE_CENTER_MISMATCH, 422)

    def test_the_coherent_template_books_and_the_other_centre_is_never_consulted(self, api):
        """Only the home centre's chair and nurse can be selected, and neither refusal left a
        visit behind on the rejected templates.

        Design: Corner/validations/template_drug_mismatch_outranks_the_center_mismatch_on_one_doubly_wrong_template
        """
        home, _away, home_chair, home_nurse, templates, patient, plan = (
            self._two_centres_and_a_doubly_wrong_template(api)
        )
        self._booking_attempt(api, home, patient, plan, templates["away_alternative"])
        self._booking_attempt(api, home, patient, plan, templates["away_reference"])

        accepted = validate_success(
            self._booking_attempt(
                api, home, patient, plan, templates["home_reference"]
            ),
            201,
        )

        assert accepted["template_id"] == templates["home_reference"]["id"]
        assert accepted["center_id"] == home["id"]
        assert accepted["chair_id"] == home_chair["id"]
        assert accepted["nurse_id"] == home_nurse["id"]

        for rejected in ("away_alternative", "away_reference"):
            _rows, meta = validate_paginated(
                api.list_appointments(
                    SCHEDULER, {"template_id": templates[rejected]["id"]}
                )
            )
            assert meta["total_count"] == 0


class TestTheSameDayRulesSwitchOnTheClockAndUrgentIsExempt:
    """Three conditional rules, one moving clock, and one class that the cutoff spares."""

    def _centre_with_a_reserved_chair(self, api: ApiClient):
        set_clock(api, "2026-08-01T10:00:00Z")
        center = create_center(api)
        create_chair(api, center["id"], "A1")
        create_chair(api, center["id"], "A2", reserved_for_urgent=True)
        nurse = create_nurse(api, center["id"], acuity_capacity_points=12)
        drug = create_drug(api)
        template = create_template(api, center["id"], drug["id"], DoseTier.MID)
        people = {}
        for key, mrn in (("routine", "MRN-0001"), ("addon", "MRN-0002"), ("urgent", "MRN-0003")):
            patient = create_patient(api, mrn=mrn, full_name=f"Pat {mrn[-1]}")
            people[key] = (patient, create_plan(api, patient["id"], drug["id"]))
        return center, nurse, template, people

    def _attempt(self, api, center, template, person, service_date, minute, booking_class):
        patient, plan = person
        return api.create_appointment(
            make_appointment_payload(
                center["id"],
                patient["id"],
                plan["id"],
                template["id"],
                service_date=service_date,
                requested_start_minute=minute,
                cycle_number=1,
                booking_class=booking_class,
            ),
            SCHEDULER,
        )

    def test_the_two_mirror_rules_pin_the_class_to_the_calendar(self, api):
        """A routine class may not name the clock's own date, and an add-on may not name any
        other date; the add-on on today's date before the cutoff is accepted.

        Design: Corner/validations/same_day_class_rules_switch_on_the_clock_and_urgent_alone_is_exempt_from_the_cutoff
        """
        center, _nurse, template, people = self._centre_with_a_reserved_chair(api)

        validate_error(
            self._attempt(
                api,
                center,
                template,
                people["routine"],
                "2026-08-01",
                660,
                BookingClass.ROUTINE,
            ),
            ApiErrorId.ERR_SAME_DAY_REQUIRES_ADDON,
            422,
        )
        validate_error(
            self._attempt(
                api,
                center,
                template,
                people["addon"],
                "2026-08-05",
                660,
                BookingClass.SAME_DAY_ADDON,
            ),
            ApiErrorId.ERR_ADDON_DATE_MISMATCH,
            422,
        )

        accepted = validate_success(
            self._attempt(
                api,
                center,
                template,
                people["addon"],
                "2026-08-01",
                660,
                BookingClass.SAME_DAY_ADDON,
            ),
            201,
        )
        assert accepted["start_minute"] == 660
        assert accepted["booking_class"] == BookingClass.SAME_DAY_ADDON

    def test_past_the_cutoff_the_add_on_is_refused_while_urgent_walks_through(self, api):
        """The only thing that changed is the clock: at minute 930 the add-on is past the
        cutoff, and the urgent class is exempt from that rule at the very same instant.

        Design: Corner/validations/same_day_class_rules_switch_on_the_clock_and_urgent_alone_is_exempt_from_the_cutoff
        """
        center, _nurse, template, people = self._centre_with_a_reserved_chair(api)
        self._attempt(
            api,
            center,
            template,
            people["addon"],
            "2026-08-01",
            660,
            BookingClass.SAME_DAY_ADDON,
        )

        set_clock(api, "2026-08-01T15:30:00Z")

        validate_error(
            self._attempt(
                api,
                center,
                template,
                people["routine"],
                "2026-08-01",
                870,
                BookingClass.SAME_DAY_ADDON,
            ),
            ApiErrorId.ERR_ADDON_CUTOFF_PASSED,
            422,
        )

        urgent = validate_success(
            self._attempt(
                api,
                center,
                template,
                people["urgent"],
                "2026-08-01",
                870,
                BookingClass.URGENT,
            ),
            201,
        )
        assert urgent["booking_class"] == BookingClass.URGENT
        assert urgent["start_minute"] == 870
        assert urgent["end_minute"] == 1110
        assert urgent["chair_id"] is not None

    def test_only_the_accepted_bookings_ever_loaded_the_roster(self, api):
        """Three refusals wrote nothing at all: the twice-refused patient holds no visit, and
        the nurse carries the load of the two accepted bookings alone.

        Design: Corner/validations/same_day_class_rules_switch_on_the_clock_and_urgent_alone_is_exempt_from_the_cutoff
        """
        center, nurse, template, people = self._centre_with_a_reserved_chair(api)
        self._attempt(
            api,
            center,
            template,
            people["routine"],
            "2026-08-01",
            660,
            BookingClass.ROUTINE,
        )
        self._attempt(
            api,
            center,
            template,
            people["addon"],
            "2026-08-05",
            660,
            BookingClass.SAME_DAY_ADDON,
        )
        self._attempt(
            api,
            center,
            template,
            people["addon"],
            "2026-08-01",
            660,
            BookingClass.SAME_DAY_ADDON,
        )
        set_clock(api, "2026-08-01T15:30:00Z")
        self._attempt(
            api,
            center,
            template,
            people["routine"],
            "2026-08-01",
            870,
            BookingClass.SAME_DAY_ADDON,
        )
        self._attempt(
            api,
            center,
            template,
            people["urgent"],
            "2026-08-01",
            870,
            BookingClass.URGENT,
        )

        _rows, meta = validate_paginated(
            api.list_appointments(
                SCHEDULER, {"patient_id": people["routine"][0]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_nurse(api, nurse["id"])["assigned_acuity_points"] == 6


class TestTheOutreachCapFollowsTheTierAndKeepsCounting:
    """The cap is re-read from the patient on every call, and the sequence never restarts."""

    def _visit_awaiting_outreach(self, api: ApiClient):
        suite = setup_suite(
            api, clock=SETUP_CLOCK, plan_overrides={"total_cycles": 12}
        )
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
        return suite, appointment

    def _lift_the_tier(self, api: ApiClient, suite):
        inject_history(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            "2026-07-13",
            ScheduleStatus.COMPLETED,
            start_minute=540,
            actual_start_minute=540,
            actual_end_minute=780,
            cycle_number=11,
        )
        inject_history(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            "2026-07-20",
            ScheduleStatus.CANCELLED,
            start_minute=540,
            late_cancellation=True,
            cycle_number=12,
        )

    def test_a_history_free_patient_accepts_a_single_contact(self, api):
        """A patient with no history reads at the bottom cadence tier, which caps outreach for
        the visit at one contact.

        Design: Corner/validations/the_outreach_cap_follows_the_patients_tier_and_recounts_the_existing_contacts
        """
        suite, appointment = self._visit_awaiting_outreach(api)

        first = validate_success(
            api.create_reminder(appointment["id"], {"channel": "SMS"}, SCHEDULER), 201
        )
        assert first["sequence_number"] == 1
        assert first["outcome"] == "NO_RESPONSE"
        assert first["patient_id"] == suite.patient_id

        response = api.create_reminder(
            appointment["id"], {"channel": "VOICE"}, SCHEDULER
        )
        validate_error(response, ApiErrorId.ERR_REMINDER_CADENCE_EXCEEDED, 409)

    def test_lifting_the_tier_reopens_the_same_visit_and_the_counter_continues(self, api):
        """A late cancellation against one clean visit divides by the two weights actually
        present, giving 27.03 and the middle tier, whose cap of three admits two further
        contacts numbered from where the first left off.

        Design: Corner/validations/the_outreach_cap_follows_the_patients_tier_and_recounts_the_existing_contacts
        """
        suite, appointment = self._visit_awaiting_outreach(api)
        validate_success(
            api.create_reminder(appointment["id"], {"channel": "SMS"}, SCHEDULER), 201
        )
        api.create_reminder(appointment["id"], {"channel": "VOICE"}, SCHEDULER)

        self._lift_the_tier(api, suite)

        risk = read_no_show_risk(api, suite.patient_id, RiskVariant.ROLLING_6)
        assert_two_decimal_places(risk["score"], 27.03)
        assert risk["reminder_tier"] == ReminderTier.ELEVATED
        assert (
            read_appointment(api, appointment["id"])["reminder_cadence_code"]
            == ReminderCadenceCode.C_ELEVATED
        )

        second = validate_success(
            api.create_reminder(appointment["id"], {"channel": "VOICE"}, SCHEDULER), 201
        )
        third = validate_success(
            api.create_reminder(appointment["id"], {"channel": "PORTAL"}, SCHEDULER), 201
        )
        assert second["sequence_number"] == 2
        assert third["sequence_number"] == 3

        validate_error(
            api.create_reminder(appointment["id"], {"channel": "SMS"}, SCHEDULER),
            ApiErrorId.ERR_REMINDER_CADENCE_EXCEEDED,
            409,
        )

        rows, meta = validate_paginated(
            api.list_reminder_contacts(SCHEDULER, {"appointment_id": appointment["id"]})
        )
        assert meta["total_count"] == 3
        assert [row["sequence_number"] for row in rows] == [1, 2, 3]

    def test_a_late_cancellation_feeds_the_score_without_becoming_a_strike(self, api):
        """Strikes count no-shows alone, so the history that lifted the cadence tier leaves
        the strike counter at zero.

        Design: Corner/validations/the_outreach_cap_follows_the_patients_tier_and_recounts_the_existing_contacts
        """
        suite, _appointment = self._visit_awaiting_outreach(api)

        self._lift_the_tier(api, suite)

        patient = read_patient(api, suite.patient_id)
        assert patient["no_show_strikes"] == 0
        assert patient["reminder_tier"] == ReminderTier.ELEVATED
        assert patient["steering_status"] == SteeringStatus.SUITE


class TestCompoundingIsBracketedByTwoTemporalRules:
    """A thirty-minute stability window leaves exactly one legal instant to mix at."""

    def _dose_awaiting_a_legal_instant(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-01T00:00:00Z",
            drug_overrides={
                "prep_stability_minutes": 30,
                "requires_lab_gate": False,
                "lab_min_anc": None,
                "lab_min_platelets": None,
            },
        )
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
        setup_approved_authorization(api, appointment["id"], approved_units=1)
        confirm_visit(api, appointment["id"])
        dose = request_dose(api, appointment["id"], 1)
        return suite, appointment, dose, lot

    def test_when_both_bars_fail_the_clinical_one_is_reported(self, api):
        """At seven the mix is both far too early and far too short-lived; the stability bar
        is a clinical safety check and outranks the temporal one.

        Design: Corner/validations/compounding_is_bracketed_by_the_too_early_floor_and_the_stability_ceiling
        """
        _suite, _appointment, dose, _lot = self._dose_awaiting_a_legal_instant(api)
        set_clock(api, "2026-08-10T07:00:00Z")

        response = api.prepare_dose(dose["id"], PHARMACIST)

        body = validate_error(response, ApiErrorId.ERR_PREP_STABILITY_SHORT, 422)
        assert body["error_id"] != ApiErrorId.ERR_PREP_TOO_EARLY

    def test_inside_the_early_floor_the_stability_bar_still_stands(self, api):
        """At half past eight the mix is late enough, but thirty minutes of stability expire
        at nine while administration does not begin until half past.

        Design: Corner/validations/compounding_is_bracketed_by_the_too_early_floor_and_the_stability_ceiling
        """
        _suite, _appointment, dose, _lot = self._dose_awaiting_a_legal_instant(api)
        set_clock(api, "2026-08-10T08:30:00Z")

        validate_error(
            api.prepare_dose(dose["id"], PHARMACIST),
            ApiErrorId.ERR_PREP_STABILITY_SHORT,
            422,
        )

        unmixed = read_preparation(api, dose["id"])
        assert unmixed["status"] == PreparationStatus.REQUESTED
        assert unmixed["prepared_at"] is None
        assert unmixed["usable_until"] is None

    def test_at_nine_both_edges_are_satisfied_on_equality(self, api):
        """Nine o'clock is exactly the visit's start instant and exactly thirty minutes before
        administration begins, so both inclusive edges hold and the dose is mixed.

        Design: Corner/validations/compounding_is_bracketed_by_the_too_early_floor_and_the_stability_ceiling
        """
        _suite, appointment, dose, lot = self._dose_awaiting_a_legal_instant(api)
        set_clock(api, "2026-08-10T07:00:00Z")
        api.prepare_dose(dose["id"], PHARMACIST)
        set_clock(api, "2026-08-10T08:30:00Z")
        api.prepare_dose(dose["id"], PHARMACIST)
        set_clock(api, "2026-08-10T09:00:00Z")

        mixed = validate_success(api.prepare_dose(dose["id"], PHARMACIST), 200)

        assert mixed["status"] == PreparationStatus.PREPARED
        assert_instant_equals(mixed["prepared_at"], "2026-08-10T09:00:00Z")
        assert_instant_equals(mixed["usable_until"], "2026-08-10T09:30:00Z")

        assert appointment["start_minute"] == 540
        assert appointment["premed_minutes"] == 30

        row = read_lot(api, lot["id"])
        assert row["units_committed"] == 1
        assert row["units_available"] == 9


class TestAnOpenReactionBlocksThePatientsNextBooking:
    """The bar reaches across appointments and is only lifted by a closed review."""

    def _infusing_visit_with_a_severe_reaction(self, api: ApiClient):
        suite = setup_suite(api, clock="2026-08-01T00:00:00Z")
        create_lot(api, suite.drug_id, units_received=10)
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
        setup_approved_authorization(api, appointment["id"], approved_units=1)
        confirm_visit(api, appointment["id"])
        set_clock(api, "2026-08-10T08:30:00Z")
        file_lab_result(
            api,
            suite.patient_id,
            collected_at="2026-08-10T07:00:00Z",
            anc_value=2.0,
            platelet_value=150,
        )
        dose = compound_dose(api, request_dose(api, appointment["id"], 1)["id"])
        check_in_visit(api, appointment["id"])
        set_clock(api, "2026-08-10T09:00:00Z")
        start_infusion(api, appointment["id"], suite.nurse_id)
        event = record_reaction(api, appointment["id"], suite.nurse_id, 3, "HOLD")
        return suite, appointment, dose, event

    def _next_cycle_attempt(self, api, suite):
        return api.create_appointment(
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

    def test_a_reported_reaction_widens_the_window_and_bars_the_next_cycle(self, api):
        """A grade three reaction adds an hour of watching and blocks readiness, and the
        booking it refuses is a different visit on a different day.

        Design: Corner/validations/an_open_reaction_review_on_the_live_visit_blocks_the_patients_next_booking
        """
        suite, appointment, _dose, event = self._infusing_visit_with_a_severe_reaction(api)

        assert event["observation_extension_minutes"] == 60
        live = read_appointment(api, appointment["id"])
        assert live["observation_extension_minutes"] == 60
        assert live["chair_minutes"] == 300
        assert live["end_minute"] == 840
        assert live["readiness_status"] == ReadinessStatus.BLOCKED

        validate_error(
            self._next_cycle_attempt(api, suite),
            ApiErrorId.ERR_ADVERSE_EVENT_OPEN,
            409,
        )

    def test_the_intermediate_review_state_does_not_lift_the_bar(self, api):
        """Opening the review moves the record along but leaves it open, and an open record is
        exactly what the booking bar reads.

        Design: Corner/validations/an_open_reaction_review_on_the_live_visit_blocks_the_patients_next_booking
        """
        suite, _appointment, _dose, event = self._infusing_visit_with_a_severe_reaction(api)
        self._next_cycle_attempt(api, suite)

        opened = open_review(api, event["id"])
        assert opened["status"] == AdverseEventStatus.UNDER_REVIEW

        validate_error(
            self._next_cycle_attempt(api, suite),
            ApiErrorId.ERR_ADVERSE_EVENT_OPEN,
            409,
        )

    def test_closing_the_review_clears_the_way_and_leaves_the_regimen_active(self, api):
        """A resume disposition closes the record without suspending anything, and the twice
        refused booking then goes through untouched.

        Design: Corner/validations/an_open_reaction_review_on_the_live_visit_blocks_the_patients_next_booking
        """
        suite, appointment, _dose, event = self._infusing_visit_with_a_severe_reaction(api)
        self._next_cycle_attempt(api, suite)
        open_review(api, event["id"])
        self._next_cycle_attempt(api, suite)

        closed = close_review(api, event["id"], ReviewOutcome.RESUME_SAME_DRUG)
        assert closed["status"] == AdverseEventStatus.CLOSED
        assert closed["review_outcome"] == ReviewOutcome.RESUME_SAME_DRUG

        booked = validate_success(self._next_cycle_attempt(api, suite), 201)
        assert booked["cycle_number"] == 2
        assert booked["service_date"] == "2026-08-17"

        assert read_plan(api, suite.plan_id)["status"] == PlanStatus.ACTIVE

        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": suite.patient_id})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {appointment["id"], booked["id"]}
