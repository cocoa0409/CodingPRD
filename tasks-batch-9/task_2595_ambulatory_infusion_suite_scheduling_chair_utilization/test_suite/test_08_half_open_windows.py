"""Two overlap axes on the same day: the buffered chair window and the unbuffered
patient window."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    DoseTier,
    SCHEDULER,
    add_patient_with_plan,
    book_appointment,
    create_plan,
    create_template,
    create_ungated_drug,
    make_appointment_payload,
    read_chair,
    read_nurse,
    setup_suite,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBufferedChairWindowPushesTheNextStart:
    """The turnover buffer is appended to the end of both intervals."""

    def _second_visit_on_the_only_chair(self, api: ApiClient):
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
        patient2, plan2 = add_patient_with_plan(api, suite, "MRN-0002", "Pat Two")
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
            suite.template_id,
            service_date="2026-08-10",
            requested_start_minute=780,
            cycle_number=1,
        )
        return suite, first, second

    def test_a_request_at_the_previous_end_minute_is_pushed_by_one_grid_step(self, api):
        """The requested minute still collides once the buffer is appended, and the
        selector takes the first candidate start that does not.

        Design: Difficulty/resource_temporal_overlap/chair_buffered_half_open_window_pushes_the_next_start_by_exactly_the_turnover_buffer
        """
        _suite, first, second = self._second_visit_on_the_only_chair(api)

        assert first["start_minute"] == 540
        assert first["end_minute"] == 780

        assert second["start_minute"] == 795
        assert second["start_minute"] != 780
        assert second["start_minute"] != 810

    def test_the_pushed_visit_legally_reuses_the_single_chair(self, api):
        """One chair serves both visits because the later window begins after the
        buffered end of the earlier one.

        Design: Difficulty/resource_temporal_overlap/chair_buffered_half_open_window_pushes_the_next_start_by_exactly_the_turnover_buffer
        """
        suite, first, second = self._second_visit_on_the_only_chair(api)

        assert first["chair_id"] == suite.chair_id("A1")
        assert second["chair_id"] == suite.chair_id("A1")
        assert second["nurse_id"] == suite.nurse_id
        assert second["end_minute"] == 1035
        assert second["chair_minutes"] == 240
        assert second["acuity_points"] == 3

    def test_both_visits_accumulate_on_the_shared_ledgers(self, api):
        """Chair minutes add up across the two committed visits, and the nurse carries
        both visits' acuity because no accounting slot ever holds more than one.

        Design: Difficulty/resource_temporal_overlap/chair_buffered_half_open_window_pushes_the_next_start_by_exactly_the_turnover_buffer
        """
        suite, _first, _second = self._second_visit_on_the_only_chair(api)

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 480
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 6


class TestUnbufferedPatientWindowRefusesOnlyRealOverlap:
    """The patient's own overlap test carries no buffer at all."""

    def _patient_on_two_regimens(self, api: ApiClient):
        suite = setup_suite(
            api,
            clock="2026-08-05T07:00:00Z",
            chair_labels=("A1", "A2"),
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
        short_plan = create_plan(
            api,
            suite.patient_id,
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
        return suite, short_template, short_plan, first

    def _attempt_short_visit(self, api: ApiClient, suite, short_template, short_plan, minute):
        return api.create_appointment(
            make_appointment_payload(
                suite.center_id,
                suite.patient_id,
                short_plan["id"],
                short_template["id"],
                service_date="2026-08-10",
                requested_start_minute=minute,
                cycle_number=1,
            ),
            SCHEDULER,
        )

    def test_a_genuinely_overlapping_second_visit_for_one_patient_is_refused(self, api):
        """A free chair could hold the window, but the patient cannot be in two places at
        once, so the refusal names the patient.

        Design: Difficulty/resource_temporal_overlap/patient_unbuffered_half_open_double_booking_refused_at_765_then_admitted_at_780
        """
        suite, short_template, short_plan, _first = self._patient_on_two_regimens(api)

        response = self._attempt_short_visit(api, suite, short_template, short_plan, 765)

        validate_error(response, ApiErrorId.ERR_PATIENT_DOUBLE_BOOKED, 409)

        assert read_chair(api, suite.chair_id("A2"))["committed_minutes"] == 0
        rows, _meta = validate_paginated(
            api.list_appointments(SCHEDULER, {"patient_id": suite.patient_id})
        )
        assert len(rows) == 1

    def test_exact_adjacency_is_legal_on_the_patient_axis(self, api):
        """Because the interval is half-open and unbuffered, a start at exactly the earlier
        visit's end minute does not overlap it.

        Design: Difficulty/resource_temporal_overlap/patient_unbuffered_half_open_double_booking_refused_at_765_then_admitted_at_780
        """
        suite, short_template, short_plan, _first = self._patient_on_two_regimens(api)
        self._attempt_short_visit(api, suite, short_template, short_plan, 765)

        response = self._attempt_short_visit(api, suite, short_template, short_plan, 780)

        admitted = validate_success(response, 201)
        assert admitted["start_minute"] == 780
        assert admitted["end_minute"] == 870
        assert admitted["chair_minutes"] == 90
        assert admitted["acuity_points"] == 2

    def test_the_admitted_visit_takes_the_second_chair_because_the_chair_rule_is_buffered(
        self, api
    ):
        """The first chair is still blocked at that minute by its buffer, so the eligible
        chair at the very first candidate start is the other one.

        Design: Difficulty/resource_temporal_overlap/patient_unbuffered_half_open_double_booking_refused_at_765_then_admitted_at_780
        """
        suite, short_template, short_plan, _first = self._patient_on_two_regimens(api)

        admitted = validate_success(
            self._attempt_short_visit(api, suite, short_template, short_plan, 780), 201
        )

        assert admitted["chair_id"] == suite.chair_id("A2")
        assert admitted["chair_id"] != suite.chair_id("A1")
        assert admitted["start_minute"] != 795

    def test_the_two_visits_load_their_own_chairs_and_one_nurse(self, api):
        """Each chair carries only its own visit's minutes while the single nurse carries
        the sum of both visits' acuity.

        Design: Difficulty/resource_temporal_overlap/patient_unbuffered_half_open_double_booking_refused_at_765_then_admitted_at_780
        """
        suite, short_template, short_plan, _first = self._patient_on_two_regimens(api)
        self._attempt_short_visit(api, suite, short_template, short_plan, 780)

        assert read_chair(api, suite.chair_id("A1"))["committed_minutes"] == 240
        assert read_chair(api, suite.chair_id("A2"))["committed_minutes"] == 90
        assert read_nurse(api, suite.nurse_id)["assigned_acuity_points"] == 5
