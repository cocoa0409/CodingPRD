"""Arithmetic read at its exact edges: the inclusive band boundary, the half-cent that
rounds up, the aggregate that maxes instead of sums, the window that caps and
renormalises, and the searches that give up on a fixed candidate count."""

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    AuthStatus,
    ChairStatus,
    DoseTier,
    LotStatus,
    MEDICAL_DIRECTOR,
    PHARMACIST,
    PreparationStatus,
    ReadinessStatus,
    ReminderTier,
    RiskVariant,
    SCHEDULER,
    ScheduleStatus,
    SteeringStatus,
    TemplateStatus,
    UtilizationVariant,
    assert_appointment_template,
    assert_instant_equals,
    assert_two_decimal_places,
    assert_utilization_report,
    book_appointment,
    compound_dose,
    create_center,
    create_chair,
    create_drug,
    create_lot,
    create_nurse,
    create_patient,
    create_plan,
    create_template,
    inject_history,
    make_appointment_payload,
    make_cancel_payload,
    make_patient_headers,
    make_template_payload,
    read_appointment,
    read_authorization,
    read_chair,
    read_lot,
    read_no_show_risk,
    read_nurse,
    read_patient,
    read_preparation,
    read_template,
    read_utilization,
    record_reaction,
    request_dose,
    run_sweep,
    set_clock,
    setup_approved_authorization,
    setup_booked_visit,
    setup_confirmed_visit,
    setup_observing_visit,
    setup_suite,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2026-08-05T07:00:00Z"
SERVICE_DATE = "2026-08-10"


class TestTemplateBuildSnapshotsTheDrugAndDerivesTwoNumbers:
    """A build copies five minute figures verbatim and computes only the acuity load and
    the stagger offset."""

    def _center_on_a_twenty_minute_grid(self, api: ApiClient):
        set_clock(api, SETUP_CLOCK)
        center = create_center(api, stagger_grid_minutes=20)
        two_point = create_drug(api)
        three_point = create_drug(api, name="Infliximab-Heavy", acuity_points=3)
        return center, two_point, three_point

    def test_a_mid_build_copies_the_drug_minutes_and_takes_its_acuity_unchanged(self, api):
        """Below the top band the acuity load is the product's own figure and the offset is
        the centre's grid exactly once.

        Design: Corner/calculations/template_build_snapshot_adds_the_high_tier_surcharge_and_doubles_the_stagger_offset
        """
        center, two_point, _three_point = self._center_on_a_twenty_minute_grid(api)

        row = validate_success(
            api.create_template(
                make_template_payload(center["id"], two_point["id"], DoseTier.MID),
                SCHEDULER,
            ),
            201,
        )

        assert_appointment_template(row)
        assert row["base_admin_minutes"] == 120
        assert row["min_admin_minutes"] == 90
        assert row["premed_minutes"] == 30
        assert row["observation_minutes_first"] == 60
        assert row["observation_minutes_subsequent"] == 30
        assert row["acuity_points"] == 2
        assert row["stagger_offset_minutes"] == 20
        assert row["status"] == TemplateStatus.ACTIVE
        assert row["version"] == 1

    def test_the_top_band_adds_one_acuity_point_yet_stays_on_the_plain_grid(self, api):
        """The surcharge lifts a two-point product to three, which is still short of the
        doubling threshold, so the offset remains a single grid step.

        Design: Corner/calculations/template_build_snapshot_adds_the_high_tier_surcharge_and_doubles_the_stagger_offset
        """
        center, two_point, _three_point = self._center_on_a_twenty_minute_grid(api)

        row = create_template(api, center["id"], two_point["id"], DoseTier.HIGH)

        assert row["acuity_points"] == 3
        assert row["stagger_offset_minutes"] == 20
        assert row["base_admin_minutes"] == 120
        assert row["min_admin_minutes"] == 90

    def test_the_surcharge_can_cross_the_threshold_and_double_the_offset(self, api):
        """A three-point product in the top band lands on four acuity points, and at four
        the offset is two grid steps rather than one.

        Design: Corner/calculations/template_build_snapshot_adds_the_high_tier_surcharge_and_doubles_the_stagger_offset
        """
        center, _two_point, three_point = self._center_on_a_twenty_minute_grid(api)

        high = create_template(api, center["id"], three_point["id"], DoseTier.HIGH)
        mid = create_template(api, center["id"], three_point["id"], DoseTier.MID)

        assert high["acuity_points"] == 4
        assert high["stagger_offset_minutes"] == 40
        assert mid["acuity_points"] == 3
        assert mid["stagger_offset_minutes"] == 20

        assert read_template(api, high["id"])["stagger_offset_minutes"] == 40

    def test_the_pharmacist_may_build_the_same_snapshot(self, api):
        """Template construction is open to both the scheduling and the pharmacy roles, and
        the snapshot does not depend on which one calls.

        Design: Corner/calculations/template_build_snapshot_adds_the_high_tier_surcharge_and_doubles_the_stagger_offset
        """
        center, two_point, _three_point = self._center_on_a_twenty_minute_grid(api)

        row = validate_success(
            api.create_template(
                make_template_payload(center["id"], two_point["id"], DoseTier.LOW),
                PHARMACIST,
            ),
            201,
        )

        assert row["acuity_points"] == 2
        assert row["stagger_offset_minutes"] == 20
        assert row["observation_minutes_first"] == 60


class TestTheLowBandRunsUpToFiveHundredMilligramsInclusive:
    """Five hundred exactly is still the bottom band; a tenth of a milligram more is not."""

    def _two_patients_astride_the_edge(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock=SETUP_CLOCK,
            chair_labels=("A1", "A2"),
            nurse_specs=[{"acuity_capacity_points": 12}],
            dose_tier=DoseTier.LOW,
            patient_overrides={"weight_kg": 50},
            plan_overrides={"dose_mg_per_kg": 10, "total_cycles": 6},
        )
        mid_template = create_template(
            api, suite.center_id, suite.drug_id, DoseTier.MID
        )
        over = create_patient(api, mrn="MRN-0002", full_name="Pat Two", weight_kg=50.01)
        over_plan = create_plan(
            api, over["id"], suite.drug_id, dose_mg_per_kg=10, total_cycles=6
        )
        return suite, mid_template, over, over_plan

    def test_exactly_five_hundred_milligrams_books_against_the_bottom_band(self, api):
        """Fifty kilograms at ten milligrams per kilogram is five hundred milligrams, which
        the inclusive upper edge keeps in the bottom band: no escalation, so the
        administration span is the product's base figure.

        Design: Corner/calculations/dose_tier_upper_edge_is_inclusive_at_exactly_five_hundred_milligrams
        """
        suite, _mid_template, _over, _over_plan = self._two_patients_astride_the_edge(api)

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

        assert appointment["chair_minutes"] == 210
        assert appointment["start_minute"] == 540
        assert appointment["end_minute"] == 750
        assert appointment["acuity_points"] == 3

    def test_a_tenth_of_a_milligram_over_the_edge_refuses_the_bottom_band_template(
        self, api
    ):
        """Fifty point zero one kilograms derives five hundred point one milligrams, which
        is past the inclusive edge, so the bottom-band template no longer matches the
        tier the booking derives for itself.

        Design: Corner/calculations/dose_tier_upper_edge_is_inclusive_at_exactly_five_hundred_milligrams
        """
        suite, _mid_template, over, over_plan = self._two_patients_astride_the_edge(api)

        response = api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                over["id"],
                over_plan["id"],
                suite.template_id,
                service_date=SERVICE_DATE,
                requested_start_minute=540,
                cycle_number=1,
            ),
            SCHEDULER,
        )

        validate_error(response, ApiErrorId.ERR_TEMPLATE_TIER_MISMATCH, 422)

        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": over["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_middle_band_template_takes_the_same_patient_with_the_escalation(self, api):
        """The only change is the band, and it adds thirty minutes of administration, which
        widens the seat window from two hundred and ten minutes to two hundred and forty.

        Design: Corner/calculations/dose_tier_upper_edge_is_inclusive_at_exactly_five_hundred_milligrams
        """
        suite, mid_template, over, over_plan = self._two_patients_astride_the_edge(api)
        book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )

        appointment = book_appointment(
            api,
            suite.center_id,
            over["id"],
            over_plan["id"],
            mid_template["id"],
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )

        assert appointment["chair_minutes"] == 240
        assert appointment["start_minute"] == 540
        assert appointment["end_minute"] == 780
        assert appointment["chair_id"] == suite.chair_id("A2")

        rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": over["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == appointment["id"]


class TestTheObservationExtensionIsAMaximumAndNeverASum:
    """Four reactions on one visit, and the window follows only the largest of them."""

    def _observing_visit(self, api: ApiClient):
        return setup_observing_visit(
            api,
            clock="2026-08-10T08:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
        )

    def test_each_record_keeps_its_own_grade_implied_extension(self, api):
        """The grade sets the extension and the bedside action can only raise it, so an
        aborted mild reaction earns a full hour of its own while a mild one on a gentler
        action earns nothing.

        Design: Corner/calculations/observation_extension_max_aggregates_across_events_and_never_sums_them
        """
        suite, observing, _prep = self._observing_visit(api)

        moderate = record_reaction(api, observing["id"], suite.nurse_id, 2, "SLOW_RATE")
        mild = record_reaction(api, observing["id"], suite.nurse_id, 1, "SLOW_RATE")
        severe = record_reaction(api, observing["id"], suite.nurse_id, 4, "HOLD")
        aborted = record_reaction(api, observing["id"], suite.nurse_id, 1, "ABORT")

        assert moderate["observation_extension_minutes"] == 30
        assert mild["observation_extension_minutes"] == 0
        assert severe["observation_extension_minutes"] == 120
        assert aborted["observation_extension_minutes"] == 60

        rows, meta = validate_paginated(
            api.list_adverse_events(SCHEDULER, {"appointment_id": observing["id"]})
        )
        assert meta["total_count"] == 4
        assert sorted(row["observation_extension_minutes"] for row in rows) == [
            0,
            30,
            60,
            120,
        ]

    def test_a_milder_second_reaction_moves_neither_the_window_nor_the_chair(self, api):
        """The visit is adjusted by the change in the maximum, and a record below the
        standing maximum changes it by zero.

        Design: Corner/calculations/observation_extension_max_aggregates_across_events_and_never_sums_them
        """
        suite, observing, _prep = self._observing_visit(api)
        assert observing["observation_extension_minutes"] == 0
        assert observing["observation_minutes"] == 60
        assert observing["chair_minutes"] == 240
        assert observing["end_minute"] == 780

        record_reaction(api, observing["id"], suite.nurse_id, 2, "SLOW_RATE")
        after_first = read_appointment(api, observing["id"])
        assert after_first["observation_extension_minutes"] == 30
        assert after_first["observation_minutes"] == 90
        assert after_first["chair_minutes"] == 270
        assert after_first["end_minute"] == 810

        record_reaction(api, observing["id"], suite.nurse_id, 1, "SLOW_RATE")
        after_mild = read_appointment(api, observing["id"])
        assert after_mild["observation_extension_minutes"] == 30
        assert after_mild["observation_minutes"] == 90
        assert after_mild["chair_minutes"] == 270
        assert after_mild["end_minute"] == 810
        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 270

    def test_the_visit_settles_on_the_largest_extension_not_the_running_total(self, api):
        """Thirty, nothing, two hours and an aborted hour sum to three and a half hours; the
        visit carries two hours, because the aggregate is a maximum.

        Design: Corner/calculations/observation_extension_max_aggregates_across_events_and_never_sums_them
        """
        suite, observing, _prep = self._observing_visit(api)

        record_reaction(api, observing["id"], suite.nurse_id, 2, "SLOW_RATE")
        record_reaction(api, observing["id"], suite.nurse_id, 1, "SLOW_RATE")
        record_reaction(api, observing["id"], suite.nurse_id, 4, "HOLD")
        record_reaction(api, observing["id"], suite.nurse_id, 1, "ABORT")

        row = read_appointment(api, observing["id"])
        assert row["observation_extension_minutes"] == 120
        assert row["observation_minutes"] == 180
        assert row["chair_minutes"] == 360
        assert row["start_minute"] == 540
        assert row["end_minute"] == 900
        assert row["schedule_status"] == ScheduleStatus.OBSERVING
        assert row["readiness_status"] == ReadinessStatus.BLOCKED

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 360
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 3


class TestThePatientShareRoundsHalfUpAtTheExactHalfCent:
    """A share of exactly seven thousand eight hundred and seventy-eight and a half cents
    rounds up, and the tier that produced it was read off the provisional figure."""

    def _late_cancellation_of_a_mixed_dose(self, api: ApiClient):
        suite, appointment = setup_confirmed_visit(
            api,
            clock=SETUP_CLOCK,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            drug_overrides={"unit_cost_cents": 22510},
        )
        lot = create_lot(api, suite.drug_id, units_received=10)
        set_clock(api, "2026-08-10T08:30:00Z")
        prep = compound_dose(api, request_dose(api, appointment["id"], 1)["id"])
        set_clock(api, "2026-08-10T08:35:00Z")
        cancelled = validate_success(
            api.cancel_appointment(
                appointment["id"],
                make_patient_headers(suite.patient_id),
                make_cancel_payload("Transport fell through"),
            ),
            200,
        )
        return suite, cancelled, prep, lot

    def test_the_half_cent_share_rounds_up_on_the_only_rounding_of_the_money_path(
        self, api
    ):
        """Base 2,500 plus waste 22,510 gives a provisional 25,010, which is above the
        inclusive 25,000 edge and therefore charges 35 percent of the waste: 7,878.5
        cents, rounded half up to 7,879, for a final 10,379.

        Design: Corner/calculations/cancellation_charge_rounds_the_patient_share_half_up_at_the_exact_half_cent
        """
        _suite, cancelled, prep, _lot = self._late_cancellation_of_a_mixed_dose(api)

        assert cancelled["schedule_status"] == ScheduleStatus.CANCELLED
        assert cancelled["late_cancellation"] is True
        assert cancelled["cancellation_charge_cents"] == 10379

        dose = read_preparation(api, prep["id"])
        assert dose["status"] == PreparationStatus.WASTED
        assert dose["waste_cost_cents"] == 22510

    def test_the_charge_propagates_to_the_ledger_the_lot_and_the_risk_figure(self, api):
        """One late cancellation is far short of the steering threshold, but it still moves
        the liability ledger, wastes exactly one unit, releases the chair and the roster,
        and refreshes the adherence reading.

        Design: Corner/calculations/cancellation_charge_rounds_the_patient_share_half_up_at_the_exact_half_cent
        """
        suite, _cancelled, _prep, booked_lot = self._late_cancellation_of_a_mixed_dose(api)

        patient = read_patient(api, suite.patient_id)
        assert patient["waste_liability_cents"] == 10379
        assert patient["steering_status"] == SteeringStatus.SUITE

        lot = read_lot(api, booked_lot["id"])
        assert lot["units_received"] == 10
        assert lot["units_committed"] == 0
        assert lot["units_administered"] == 0
        assert lot["units_wasted"] == 1
        assert lot["units_returned"] == 0
        assert lot["units_available"] == 9
        assert lot["status"] == LotStatus.AVAILABLE

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 0

        risk = read_no_show_risk(api, suite.patient_id)
        assert risk["considered_appointment_count"] == 1
        assert risk["score"] == pytest.approx(50.00, abs=0.005)
        assert risk["reminder_tier"] == ReminderTier.INTENSIVE


class TestScheduledUtilizationCountsOnlyServiceableChairs:
    """Withdrawing a chair from service raises the reported figure, and an abandoned visit
    never reaches the numerator."""

    def _one_live_visit_and_one_abandoned_row(self, api: ApiClient):
        suite = setup_suite(api, clock=SETUP_CLOCK, chair_labels=("A1", "A2"))
        live = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )
        walked = create_patient(api, mrn="MRN-0002", full_name="Pat Two")
        walked_plan = create_plan(api, walked["id"], suite.drug_id)
        inject_history(
            api,
            suite.center_id,
            walked["id"],
            walked_plan["id"],
            suite.template_id,
            SERVICE_DATE,
            ScheduleStatus.NO_SHOW,
            chair_minutes=240,
        )
        return suite, live

    def test_the_omitted_variant_reads_scheduled_and_skips_the_abandoned_row(self, api):
        """Two serviceable chairs over an eleven-hour open span give 1,320 available
        minutes, of which only the live visit's planned 240 are occupied; the no-showed
        row on the same day contributes nothing and is not counted.

        Design: Corner/calculations/scheduled_utilization_counts_only_available_chairs_and_ignores_abandoned_visits
        """
        suite, _live = self._one_live_visit_and_one_abandoned_row(api)

        report = read_utilization(api, suite.center_id, SERVICE_DATE)

        assert_utilization_report(report)
        assert report["variant"] == UtilizationVariant.SCHEDULED
        assert report["available_chair_minutes"] == 1320
        assert report["occupied_chair_minutes"] == 240
        assert_two_decimal_places(report["utilization_pct"], 18.18)
        assert report["appointment_count"] == 1
        assert report["biosimilar_savings_cents"] == 0

    def test_withdrawing_a_chair_shrinks_the_denominator_and_lifts_the_figure(self, api):
        """The out-of-service chair leaves the denominator entirely, so the same 240
        occupied minutes now read against 660 rather than 1,320.

        Design: Corner/calculations/scheduled_utilization_counts_only_available_chairs_and_ignores_abandoned_visits
        """
        suite, live = self._one_live_visit_and_one_abandoned_row(api)

        validate_success(
            api.update_chair(
                suite.chair_id("A2"), {"status": ChairStatus.OUT_OF_SERVICE}, SCHEDULER
            ),
            200,
        )

        report = read_utilization(api, suite.center_id, SERVICE_DATE)
        assert report["available_chair_minutes"] == 660
        assert report["occupied_chair_minutes"] == 240
        assert_two_decimal_places(report["utilization_pct"], 36.36)
        assert report["appointment_count"] == 1

        untouched = read_appointment(api, live["id"])
        assert untouched["chair_id"] == suite.chair_id("A1")
        assert untouched["schedule_status"] == ScheduleStatus.TENTATIVE

    def test_an_empty_denominator_reports_exactly_zero_rather_than_failing(self, api):
        """With every chair withdrawn the division has no denominator, and the report is
        pinned to 0.00 while the released visit keeps its planned length in the
        numerator.

        Design: Corner/calculations/scheduled_utilization_counts_only_available_chairs_and_ignores_abandoned_visits
        """
        suite, live = self._one_live_visit_and_one_abandoned_row(api)

        for label in ("A2", "A1"):
            validate_success(
                api.update_chair(
                    suite.chair_id(label),
                    {"status": ChairStatus.OUT_OF_SERVICE},
                    SCHEDULER,
                ),
                200,
            )

        report = validate_success(
            api.get_utilization(
                suite.center_id, MEDICAL_DIRECTOR, {"service_date": SERVICE_DATE}
            ),
            200,
        )
        assert report["available_chair_minutes"] == 0
        assert report["occupied_chair_minutes"] == 240
        assert_two_decimal_places(report["utilization_pct"], 0.00)
        assert report["appointment_count"] == 1

        released = read_appointment(api, live["id"])
        assert released["chair_id"] is None
        assert released["nurse_id"] is None
        assert released["chair_minutes"] == 240
        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 0
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 0


class TestTheRollingWindowCapsAtSixRowsAndRenormalises:
    """Six weights for six rows, and a shorter history divides by the weights it has."""

    def test_the_seventh_oldest_row_falls_outside_the_window(self, api):
        """Six completed visits are the whole window even though a no-show exists on an
        earlier date and was recorded last, because the ordering is by service date
        descending rather than by insertion.

        Design: Corner/calculations/rolling_six_window_caps_at_six_rows_and_renormalises_a_short_window
        """
        suite = setup_suite(
            api, clock="2026-08-01T00:00:00Z", plan_overrides={"total_cycles": 12}
        )
        for service_date in (
            "2026-06-08",
            "2026-06-15",
            "2026-06-22",
            "2026-06-29",
            "2026-07-06",
            "2026-07-13",
        ):
            inject_history(
                api,
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date,
                ScheduleStatus.COMPLETED,
            )
        inject_history(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            "2026-06-01",
            ScheduleStatus.NO_SHOW,
        )

        risk = read_no_show_risk(api, suite.patient_id)
        assert risk["variant"] == RiskVariant.ROLLING_6
        assert risk["considered_appointment_count"] == 6
        assert_two_decimal_places(risk["score"], 0.00)
        assert risk["reminder_tier"] == ReminderTier.STANDARD

        patient = read_patient(api, suite.patient_id)
        assert_two_decimal_places(patient["no_show_risk_score"], 0.00)
        assert patient["reminder_tier"] == ReminderTier.STANDARD
        assert patient["completed_appointment_count"] == 6
        assert patient["no_show_strikes"] == 1
        assert patient["steering_status"] == SteeringStatus.SUITE

    def test_a_two_row_history_divides_by_the_weights_actually_present(self, api):
        """The window holds only two rows, so the divisor is 185 rather than the full 375:
        a full-value miss at weight 100 against a clean visit at weight 85 scores 54.05,
        which is squarely in the top adherence band.

        Design: Corner/calculations/rolling_six_window_caps_at_six_rows_and_renormalises_a_short_window
        """
        suite = setup_suite(api, clock="2026-08-01T00:00:00Z")
        inject_history(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            "2026-07-13",
            ScheduleStatus.COMPLETED,
        )
        inject_history(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            "2026-07-20",
            ScheduleStatus.NO_SHOW,
        )

        risk = read_no_show_risk(api, suite.patient_id)
        assert risk["considered_appointment_count"] == 2
        assert_two_decimal_places(risk["score"], 54.05)
        assert risk["reminder_tier"] == ReminderTier.INTENSIVE

        patient = read_patient(api, suite.patient_id)
        assert_two_decimal_places(patient["no_show_risk_score"], 54.05)
        assert patient["reminder_tier"] == ReminderTier.INTENSIVE
        assert patient["completed_appointment_count"] == 1
        assert patient["no_show_strikes"] == 1


class TestLotSelectionIsFirstExpiryFirstOut:
    """Three lots in deliberately unhelpful creation order, and one dose that will not
    split across two of them."""

    def _three_lots_of_differing_expiry(self, api: ApiClient):
        suite, appointment = setup_booked_visit(
            api,
            clock="2026-08-01T00:00:00Z",
            service_date=SERVICE_DATE,
            requested_start_minute=540,
        )
        november = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-NOV",
            units_received=10,
            expires_on="2026-11-01T00:00:00Z",
        )
        october = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-OCT",
            units_received=5,
            expires_on="2026-10-01T00:00:00Z",
        )
        september = create_lot(
            api,
            suite.drug_id,
            lot_number="LOT-SEP",
            units_received=1,
            expires_on="2026-09-01T00:00:00Z",
        )
        return suite, appointment, november, october, september

    def test_the_stock_closest_to_expiry_is_consumed_first_and_depletes(self, api):
        """The soonest-expiring lot was registered last, and it is still the one taken,
        because the ordering is on expiry rather than on creation; its single unit takes
        it straight to depleted.

        Design: Corner/calculations/lot_selection_is_first_expiry_first_out_and_never_splits_a_dose_across_lots
        """
        _suite, appointment, november, october, september = (
            self._three_lots_of_differing_expiry(api)
        )

        dose = request_dose(api, appointment["id"], 1)

        assert dose["drug_lot_id"] == september["id"]
        assert dose["status"] == PreparationStatus.REQUESTED

        soonest = read_lot(api, september["id"])
        assert soonest["units_committed"] == 1
        assert soonest["units_available"] == 0
        assert soonest["status"] == LotStatus.DEPLETED

        assert read_lot(api, october["id"])["units_available"] == 5
        assert read_lot(api, november["id"])["units_available"] == 10

    def test_a_depleted_lot_leaves_the_pool_and_the_next_expiry_absorbs_the_dose(self, api):
        """With the soonest expiry depleted the candidate pool starts one row later, and the
        further-out lot is untouched.

        Design: Corner/calculations/lot_selection_is_first_expiry_first_out_and_never_splits_a_dose_across_lots
        """
        _suite, appointment, november, october, _september = (
            self._three_lots_of_differing_expiry(api)
        )
        request_dose(api, appointment["id"], 1)

        dose = request_dose(api, appointment["id"], 3)

        assert dose["drug_lot_id"] == october["id"]

        middle = read_lot(api, october["id"])
        assert middle["units_committed"] == 3
        assert middle["units_available"] == 2
        assert middle["status"] == LotStatus.AVAILABLE

        latest = read_lot(api, november["id"])
        assert latest["units_committed"] == 0
        assert latest["units_available"] == 10

    def test_a_request_larger_than_the_nearest_lot_skips_it_rather_than_splitting_it(
        self, api
    ):
        """Two units remain on the nearer expiry and six are asked for; partial fills are
        not permitted, so the whole request goes to the later lot and the nearer one keeps
        its two units exactly.

        Design: Corner/calculations/lot_selection_is_first_expiry_first_out_and_never_splits_a_dose_across_lots
        """
        _suite, appointment, november, october, september = (
            self._three_lots_of_differing_expiry(api)
        )
        first = request_dose(api, appointment["id"], 1)
        second = request_dose(api, appointment["id"], 3)

        third = request_dose(api, appointment["id"], 6)

        assert third["drug_lot_id"] == november["id"]

        latest = read_lot(api, november["id"])
        assert latest["units_committed"] == 6
        assert latest["units_available"] == 4
        assert latest["status"] == LotStatus.AVAILABLE

        assert read_lot(api, october["id"])["units_available"] == 2
        assert read_lot(api, september["id"])["units_available"] == 0

        rows, meta = validate_paginated(
            api.list_drug_preparations(
                PHARMACIST, {"appointment_id": appointment["id"]}
            )
        )
        assert meta["total_count"] == 3
        assert {row["id"] for row in rows} == {first["id"], second["id"], third["id"]}
        assert all(row["status"] == PreparationStatus.REQUESTED for row in rows)


class TestTheSelectorGivesUpAfterNineCandidateStarts:
    """Eight further grid steps and no more, even when the tenth would have worked."""

    def _one_chair_blocked_until_the_tenth_candidate(self, api: ApiClient):
        set_clock(api, SETUP_CLOCK)
        center = create_center(
            api,
            open_minute=420,
            close_minute=1140,
            turnover_buffer_minutes=15,
            stagger_grid_minutes=15,
        )
        create_chair(api, center["id"], "A1")
        nurse = create_nurse(
            api,
            center["id"],
            shift_start_minute=420,
            shift_end_minute=1140,
            acuity_capacity_points=6,
        )
        drug = create_drug(api)
        template = create_template(api, center["id"], drug["id"], DoseTier.MID)
        blocked = create_patient(api, mrn="MRN-0001", full_name="Pat One")
        blocked_plan = create_plan(api, blocked["id"], drug["id"])
        waiting = create_patient(api, mrn="MRN-0002", full_name="Pat Two")
        waiting_plan = create_plan(api, waiting["id"], drug["id"])
        blocker = book_appointment(
            api,
            center["id"],
            blocked["id"],
            blocked_plan["id"],
            template["id"],
            service_date=SERVICE_DATE,
            requested_start_minute=420,
            cycle_number=1,
        )
        assert blocker["start_minute"] == 420
        assert blocker["end_minute"] == 660
        return center, nurse, template, waiting, waiting_plan, blocker

    def test_nine_colliding_candidates_exhaust_the_search(self, api):
        """The occupied window buffered on its end reaches 675, and the ninth candidate is
        only 540, so every candidate collides and the sole chair runs out.

        Design: Corner/calculations/selector_gives_up_after_nine_grid_candidates_even_though_a_later_start_is_legal
        """
        center, _nurse, template, waiting, waiting_plan, _blocker = (
            self._one_chair_blocked_until_the_tenth_candidate(api)
        )

        response = api.create_appointment(
            make_appointment_payload(
                center["id"],
                waiting["id"],
                waiting_plan["id"],
                template["id"],
                service_date=SERVICE_DATE,
                requested_start_minute=420,
                cycle_number=1,
            ),
            SCHEDULER,
        )

        validate_error(response, ApiErrorId.ERR_NO_CHAIR_CAPACITY, 409)

        _rows, meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": waiting["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_same_request_one_grid_step_later_is_seated_immediately(self, api):
        """A start of 675 is exactly the buffered end of the earlier occupancy, which the
        half-open rule permits, so the identical booking succeeds on the same chair and
        the same nurse the moment it is asked for outside the nine-candidate reach.

        Design: Corner/calculations/selector_gives_up_after_nine_grid_candidates_even_though_a_later_start_is_legal
        """
        center, nurse, template, waiting, waiting_plan, blocker = (
            self._one_chair_blocked_until_the_tenth_candidate(api)
        )

        seated = book_appointment(
            api,
            center["id"],
            waiting["id"],
            waiting_plan["id"],
            template["id"],
            service_date=SERVICE_DATE,
            requested_start_minute=675,
            cycle_number=1,
        )

        assert seated["start_minute"] == 675
        assert seated["end_minute"] == 915
        assert seated["chair_id"] == blocker["chair_id"]
        assert seated["nurse_id"] == nurse["id"]
        assert seated["schedule_status"] == ScheduleStatus.TENTATIVE

        assert read_chair(api, blocker["chair_id"])["committed_minutes"] == 480
        assert read_nurse(api, nurse["id"])["assigned_acuity_points"] == 6


class TestOneSweepExpiresCoverageAndStillMarksTheNoShow:
    """Two ordered steps of the same run touch the same visit, and the expiry comparison
    is inclusive of the instant itself."""

    def _two_visits_whose_coverage_straddles_the_sweep_instant(self, api: ApiClient):
        suite = setup_suite(api, clock="2026-08-01T00:00:00Z")
        near = book_appointment(
            api,
            suite.center_id,
            suite.patient_id,
            suite.plan_id,
            suite.template_id,
            service_date=SERVICE_DATE,
            requested_start_minute=540,
            cycle_number=1,
        )
        later_patient = create_patient(api, mrn="MRN-0002", full_name="Pat Two")
        later_plan = create_plan(api, later_patient["id"], suite.drug_id)
        far = book_appointment(
            api,
            suite.center_id,
            later_patient["id"],
            later_plan["id"],
            suite.template_id,
            service_date="2026-09-15",
            requested_start_minute=540,
            cycle_number=1,
        )
        near_auth = setup_approved_authorization(api, near["id"], approved_units=1)
        set_clock(api, "2026-08-01T00:00:01Z")
        far_auth = setup_approved_authorization(api, far["id"], approved_units=1)
        set_clock(api, "2026-08-31T00:00:00Z")
        counters = run_sweep(api, suite.center_id, SERVICE_DATE)
        return suite, near, far, near_auth, far_auth, later_patient, counters

    def test_the_inclusive_comparison_catches_one_authorization_and_spares_its_sibling(
        self, api
    ):
        """Thirty days after decisions one second apart, the two expiry instants straddle
        the sweep clock: the one landing exactly on it expires, the one a second later
        does not.

        Design: Corner/calculations/one_sweep_expires_the_authorization_at_the_inclusive_instant_and_still_no_shows_the_visit
        """
        _suite, _near, _far, near_auth, far_auth, _later, counters = (
            self._two_visits_whose_coverage_straddles_the_sweep_instant(api)
        )

        assert_instant_equals(near_auth["expires_at"], "2026-08-31T00:00:00Z")
        assert_instant_equals(far_auth["expires_at"], "2026-08-31T00:00:01Z")

        assert counters["expired_authorization_count"] == 1
        assert read_authorization(api, near_auth["id"])["status"] == AuthStatus.EXPIRED
        assert read_authorization(api, far_auth["id"])["status"] == AuthStatus.APPROVED

    def test_the_same_run_also_marks_the_no_show_and_reports_both_counters(self, api):
        """A run that stopped at the first step which changed something would report one of
        the two counters as zero; the checkpoint runs every step, so coverage is withdrawn
        and the visit is no-showed on one call.

        Design: Corner/calculations/one_sweep_expires_the_authorization_at_the_inclusive_instant_and_still_no_shows_the_visit
        """
        _suite, near, far, _near_auth, _far_auth, _later, counters = (
            self._two_visits_whose_coverage_straddles_the_sweep_instant(api)
        )

        assert counters["expired_lot_count"] == 0
        assert counters["wasted_preparation_count"] == 0
        assert counters["expired_authorization_count"] == 1
        assert counters["no_show_count"] == 1

        missed = read_appointment(api, near["id"])
        assert missed["schedule_status"] == ScheduleStatus.NO_SHOW
        assert missed["readiness_status"] == ReadinessStatus.PENDING

        untouched = read_appointment(api, far["id"])
        assert untouched["schedule_status"] == ScheduleStatus.TENTATIVE

    def test_the_no_show_releases_the_chair_and_rewrites_only_that_patients_profile(
        self, api
    ):
        """The abandoned visit gives its minutes back, leaving the chair holding only the
        September visit, and the strike cascade lands on one patient alone.

        Design: Corner/calculations/one_sweep_expires_the_authorization_at_the_inclusive_instant_and_still_no_shows_the_visit
        """
        suite, _near, _far, _near_auth, _far_auth, later_patient, _counters = (
            self._two_visits_whose_coverage_straddles_the_sweep_instant(api)
        )

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240

        missed_patient = read_patient(api, suite.patient_id)
        assert missed_patient["no_show_strikes"] == 1
        assert_two_decimal_places(missed_patient["no_show_risk_score"], 100.00)
        assert missed_patient["reminder_tier"] == ReminderTier.INTENSIVE
        assert missed_patient["steering_status"] == SteeringStatus.SUITE

        spared = read_patient(api, later_patient["id"])
        assert spared["no_show_strikes"] == 0
        assert spared["reminder_tier"] == ReminderTier.STANDARD


class TestTheOmittedVariantResolvesToTheRollingReading:
    """A payer-facing zero must never be allowed to soften the outreach cadence."""

    def _six_terminal_visits_all_in_the_previous_quarter(self, api: ApiClient):
        suite = setup_suite(
            api, clock="2026-08-01T00:00:00Z", plan_overrides={"total_cycles": 12}
        )
        rows = (
            ("2026-06-20", ScheduleStatus.NO_SHOW, {}),
            ("2026-06-13", ScheduleStatus.CANCELLED, {"late_cancellation": True}),
            ("2026-06-06", ScheduleStatus.COMPLETED, {}),
            ("2026-05-30", ScheduleStatus.CANCELLED, {"late_cancellation": False}),
            ("2026-05-23", ScheduleStatus.COMPLETED, {}),
            ("2026-05-16", ScheduleStatus.NO_SHOW, {}),
        )
        for service_date, status, extra in rows:
            inject_history(
                api,
                suite.center_id,
                suite.patient_id,
                suite.plan_id,
                suite.template_id,
                service_date,
                status,
                **extra,
            )
        return suite

    def test_omitting_the_variable_returns_the_recency_weighted_figure(self, api):
        """A full-value miss at weight 100, a late cancellation at 85, an early one at 55
        and an older miss at 25 give 181.25 over the full 375 of weights, which is 48.33.

        Design: Corner/calculations/omitted_variant_defaults_to_rolling_six_and_the_tier_never_follows_the_quarter
        """
        suite = self._six_terminal_visits_all_in_the_previous_quarter(api)

        risk = read_no_show_risk(api, suite.patient_id)

        assert risk["patient_id"] == suite.patient_id
        assert risk["variant"] == RiskVariant.ROLLING_6
        assert_two_decimal_places(risk["score"], 48.33)
        assert risk["considered_appointment_count"] == 6
        assert risk["reminder_tier"] == ReminderTier.INTENSIVE

        patient = read_patient(api, suite.patient_id)
        assert_two_decimal_places(patient["no_show_risk_score"], 48.33)
        assert patient["reminder_tier"] == ReminderTier.INTENSIVE
        assert patient["no_show_strikes"] == 2
        assert patient["steering_status"] == SteeringStatus.SUITE

    def test_an_empty_quarter_scores_zero_while_the_tier_stays_on_the_rolling_score(
        self, api
    ):
        """Every terminal visit sits in the previous quarter, so the quarter reading has no
        input at all — and the cadence tier in that very response is still the one the
        rolling figure implies.

        Design: Corner/calculations/omitted_variant_defaults_to_rolling_six_and_the_tier_never_follows_the_quarter
        """
        suite = self._six_terminal_visits_all_in_the_previous_quarter(api)

        quarter = validate_success(
            api.get_no_show_risk(
                suite.patient_id,
                make_patient_headers(suite.patient_id),
                {"variant": RiskVariant.QUARTER_TO_DATE},
            ),
            200,
        )

        assert quarter["patient_id"] == suite.patient_id
        assert quarter["variant"] == RiskVariant.QUARTER_TO_DATE
        assert_two_decimal_places(quarter["score"], 0.00)
        assert quarter["considered_appointment_count"] == 0
        assert quarter["reminder_tier"] == ReminderTier.INTENSIVE
