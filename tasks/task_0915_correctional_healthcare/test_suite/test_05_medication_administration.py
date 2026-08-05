"""Recording doses: DOT/KOP observation discipline, segregation of duties, the dose
window boundaries and the rungs that pre-empt them."""

from test_helpers import (
    ApiErrorId,
    assert_adherence_equals,
    assert_medication_administration,
    fixtures as fx,
    make_nurse_headers,
    validate_error,
    validate_success,
)


class TestObservationDiscipline:
    def test_keep_on_person_order_forbids_the_observed_swallow_field(self, api, nurse_headers):
        """PRD §3.4: "On a `KOP` order the rule inverts and broadens: `observed_swallow`
        must be absent from the body for **every** outcome, and supplying it is rejected with
        `ERR_KOP_OBSERVATION_FORBIDDEN` (422)."

        Design: Corner/validations/kop_order_rejects_observed_swallow_field
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2320", full_name="Yan Aoki", booked_at="2026-05-01T00:00:00Z"
        )
        order = fx.write_medication_order(
            inmate["id"],
            drug_name="Lisinopril",
            drug_class="CHRONIC_MAINTENANCE",
            route_mode="KOP",
        )
        dose = fx.schedule_dose(order["id"], "2026-05-01T08:00:00Z")
        fx.set_clock("2026-05-01T08:00:00Z")

        rejected = api.record_administration(
            dose["id"], {"outcome": "ADMINISTERED", "observed_swallow": True}, nurse_headers
        )
        validate_error(rejected, ApiErrorId.ERR_KOP_OBSERVATION_FORBIDDEN.value, 422)

        accepted = api.record_administration(
            dose["id"], {"outcome": "ADMINISTERED"}, nurse_headers
        )
        data = validate_success(accepted, 200)
        assert_medication_administration(data)
        assert data["outcome"] == "ADMINISTERED"


class TestConsecutiveRefusalEscalation:
    def test_third_consecutive_refusal_escalates_and_an_administered_dose_resets_the_counter(
        self, api
    ):
        """PRD §3.4: "`REFUSED` stamps `acted_at`, leaves `timing_class` null, increments
        `consecutive_refused_count` by 1 and leaves `consecutive_missed_count` untouched."
        PRD §3.4: "On either of the two failure outcomes, an incremented counter that reaches
        3 or more sets `escalated_to_prescriber` to true."
        PRD §3.4: "`ADMINISTERED` stamps `acted_at` from the current clock, classifies the
        dose window as described below, and resets **both** consecutive counters to 0."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_consecutive_refusals_escalate_to_prescriber
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2400", full_name="Hana Kuo", booked_at="2026-05-01T00:00:00Z"
        )
        order, doses = fx.setup_dot_order_with_doses(
            inmate["id"],
            [
                "2026-05-01T08:00:00Z",
                "2026-05-02T08:00:00Z",
                "2026-05-03T08:00:00Z",
                "2026-05-04T08:00:00Z",
            ],
            drug_name="Sertraline",
            drug_class="PSYCHOTROPIC",
            doses_per_day=1,
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-10T00:00:00Z",
        )

        fx.record_dose(doses[0]["id"], {"outcome": "REFUSED"})
        fx.record_dose(doses[1]["id"], {"outcome": "REFUSED"})
        after_two = fx.read_order(order["id"])
        assert after_two["consecutive_refused_count"] == 2
        assert after_two["escalated_to_prescriber"] is False

        fx.record_dose(doses[2]["id"], {"outcome": "REFUSED"})
        after_three = fx.read_order(order["id"])
        assert after_three["consecutive_refused_count"] == 3
        assert after_three["escalated_to_prescriber"] is True

        fx.set_clock("2026-05-04T08:00:00Z")
        fx.record_dose(doses[3]["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
        final = fx.read_order(order["id"])
        assert final["consecutive_refused_count"] == 0
        assert final["consecutive_missed_count"] == 0
        assert final["escalated_to_prescriber"] is True
        assert_adherence_equals(final["adherence_pct"], 25.00)


class TestParentOrderStateGate:
    def test_held_parent_order_refuses_a_legally_scheduled_dose(self, api, nurse_headers):
        """PRD §3.4: "The row itself must still be `SCHEDULED`, and the parent order must be
        `ACTIVE` — a `HELD`, `DISCONTINUED` or `COMPLETED` parent refuses the record with
        `ERR_ORDER_NOT_ACTIVE` (409) even though the dose row is perfectly legal in itself."

        Design: Difficulty/cross_entity_state_dependency/administration_record_gated_by_parent_order_state
        """
        scenario = fx.setup_held_order_with_scheduled_dose(booking_number="D-1170")
        resp = api.record_administration(
            scenario["dose"]["id"],
            {"outcome": "ADMINISTERED", "observed_swallow": True},
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACTIVE.value, 409)
        row = fx.read_administration(scenario["order"]["id"], scenario["dose"]["id"])
        assert row["outcome"] == "SCHEDULED"

    def test_resuming_the_parent_order_lets_the_identical_record_succeed(self, api, nurse_headers):
        """PRD §3.4: "Passing true moves an `ACTIVE` order to `HELD`; passing false moves a
        `HELD` order back to `ACTIVE`, and the resume additionally requires the patient to be
        `IN_CUSTODY`."
        PRD §3.4: "The row itself must still be `SCHEDULED`, and the parent order must be
        `ACTIVE` — a `HELD`, `DISCONTINUED` or `COMPLETED` parent refuses the record with
        `ERR_ORDER_NOT_ACTIVE` (409) even though the dose row is perfectly legal in itself."

        Design: Difficulty/cross_entity_state_dependency/administration_record_gated_by_parent_order_state
        """
        scenario = fx.setup_held_order_with_scheduled_dose(booking_number="D-1171")
        validate_error(
            api.record_administration(
                scenario["dose"]["id"],
                {"outcome": "ADMINISTERED", "observed_swallow": True},
                nurse_headers,
            ),
            ApiErrorId.ERR_ORDER_NOT_ACTIVE.value,
            409,
        )
        fx.resume_order(scenario["order"]["id"])

        resp = api.record_administration(
            scenario["dose"]["id"],
            {"outcome": "ADMINISTERED", "observed_swallow": True},
            nurse_headers,
        )
        data = validate_success(resp, 200)
        assert data["outcome"] == "ADMINISTERED"
        assert data["timing_class"] == "ON_TIME"
        assert_adherence_equals(fx.read_order(scenario["order"]["id"])["adherence_pct"], 100.00)


class TestLadderPreemption:
    def test_cross_entity_order_state_pre_empts_segregation_of_duties(self, api):
        """PRD §2.5: "All checks in this system belong to one global ladder of fourteen
        rungs, evaluated strictly in ascending order. The first rung that fails determines the
        response, and no rung below it is evaluated at all."
        PRD §2.5: "**Cross-entity state.** A *different* entity's state must permit the
        transition. Recording an administration against a parent order that is not `ACTIVE`
        yields `ERR_ORDER_NOT_ACTIVE` (409); creating a transport or assigning an escort
        against a referral that is not `AUTHORIZED` yields `ERR_REFERRAL_NOT_AUTHORIZED`
        (409); releasing an inmate with no `FINALIZED` release plan yields `ERR_INVALID_STATE`
        (409)."
        PRD §2.5: "**Segregation of duties.** The acting user is not the same person who
        performed the conflicting earlier step. Failure yields `ERR_SEGREGATION_OF_DUTIES`
        (403)."

        Design: Difficulty/priority_pair_validation_conflict/order_not_active_preempts_segregation_of_duties
        """
        scenario = fx.setup_held_order_with_scheduled_dose(
            prescriber_id="u-101", booking_number="D-1120"
        )
        resp = api.record_administration(
            scenario["dose"]["id"],
            {"outcome": "ADMINISTERED", "observed_swallow": True},
            make_nurse_headers("u-101"),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACTIVE.value, 409)
        row = fx.read_administration(scenario["order"]["id"], scenario["dose"]["id"])
        assert row["outcome"] == "SCHEDULED"

    def test_segregation_of_duties_surfaces_once_the_order_is_active_again(self, api):
        """PRD §3.4: "Finally, the person recording the dose may not be the person who wrote
        the order: when the acting `X-User-ID` equals the order's `prescriber_user_id`, the
        record is refused with `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Difficulty/priority_pair_validation_conflict/order_not_active_preempts_segregation_of_duties
        """
        scenario = fx.setup_held_order_with_scheduled_dose(
            prescriber_id="u-101", booking_number="D-1121"
        )
        fx.resume_order(scenario["order"]["id"], prescriber_id="u-101")
        assert fx.read_order(scenario["order"]["id"])["status"] == "ACTIVE"

        resp = api.record_administration(
            scenario["dose"]["id"],
            {"outcome": "ADMINISTERED", "observed_swallow": True},
            make_nurse_headers("u-101"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        row = fx.read_administration(scenario["order"]["id"], scenario["dose"]["id"])
        assert row["outcome"] == "SCHEDULED"

    def test_frozen_records_pre_empt_the_missing_observation_check(self, api, nurse_headers):
        """PRD §2.5: "**This rung sits deliberately high and pre-empts all nine rungs below
        it.** A frozen inmate returns `ERR_RECORDS_FROZEN` even when the very same request
        also carries a stale version, a malformed payload, an out-of-range enum, an illegal
        target state, an expired temporal window or a counter already at its cap.
        Litigation-hold integrity outranks every downstream correctness concern."

        Design: Difficulty/priority_pair_validation_conflict/frozen_records_preempts_dot_observation_check
        """
        scenario = fx.setup_frozen_patient_with_scheduled_dot_dose()
        assert fx.read_inmate(scenario["inmate"]["id"])["records_state"] == "FROZEN"

        resp = api.record_administration(
            scenario["dose"]["id"], {"outcome": "ADMINISTERED"}, nurse_headers
        )
        validate_error(resp, ApiErrorId.ERR_RECORDS_FROZEN.value, 409)
        row = fx.read_administration(scenario["order"]["id"], scenario["dose"]["id"])
        assert row["outcome"] == "SCHEDULED"
        assert_adherence_equals(fx.read_order(scenario["order"]["id"])["adherence_pct"], 0.00)

    def test_lifting_the_freeze_exposes_the_missing_observation_error(self, api, nurse_headers):
        """PRD §3.4: "On a `DOT` order, `observed_swallow` must be present in the body **when
        and only when** the recorded outcome is `ADMINISTERED`; a `REFUSED` or `MISSED`
        outcome never requires it, and an administered dose without it is rejected with
        `ERR_DOT_OBSERVATION_REQUIRED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/frozen_records_preempts_dot_observation_check
        """
        scenario = fx.setup_frozen_patient_with_scheduled_dot_dose()
        validate_error(
            api.record_administration(
                scenario["dose"]["id"], {"outcome": "ADMINISTERED"}, nurse_headers
            ),
            ApiErrorId.ERR_RECORDS_FROZEN.value,
            409,
        )
        fx.unfreeze_records(scenario["inmate"]["id"])

        resp = api.record_administration(
            scenario["dose"]["id"], {"outcome": "ADMINISTERED"}, nurse_headers
        )
        validate_error(resp, ApiErrorId.ERR_DOT_OBSERVATION_REQUIRED.value, 422)
        row = fx.read_administration(scenario["order"]["id"], scenario["dose"]["id"])
        assert row["outcome"] == "SCHEDULED"


class TestDoseWindowBoundaries:
    def test_exactly_sixty_minutes_late_is_still_on_time(self, api):
        """PRD §3.4: "From there up to and including 60 minutes late the dose is `ON_TIME`,
        so a difference of exactly 60 counts as on time and 61 does not. From 61 minutes
        through and including 120 minutes late the dose is `LATE`, so exactly 120 is `LATE`
        and 121 is `MISSED_WINDOW`."

        Design: Difficulty/boundary_precision_check/dose_window_60_minutes_on_time_61_minutes_late
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1140", full_name="Quinn Reyes", booked_at="2026-05-01T00:00:00Z"
        )
        order, doses = fx.setup_dot_order_with_doses(
            inmate["id"],
            ["2026-05-01T08:00:00Z"],
            drug_name="Sertraline",
            drug_class="PSYCHOTROPIC",
            doses_per_day=2,
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-10T00:00:00Z",
        )
        fx.set_clock("2026-05-01T09:00:00Z")
        data = fx.record_dose(doses[0]["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
        assert data["timing_class"] == "ON_TIME"
        assert_adherence_equals(fx.read_order(order["id"])["adherence_pct"], 100.00)

    def test_sixty_one_minutes_late_crosses_into_the_late_band(self, api):
        """PRD §3.4: "From there up to and including 60 minutes late the dose is `ON_TIME`,
        so a difference of exactly 60 counts as on time and 61 does not. From 61 minutes
        through and including 120 minutes late the dose is `LATE`, so exactly 120 is `LATE`
        and 121 is `MISSED_WINDOW`."

        Design: Difficulty/boundary_precision_check/dose_window_60_minutes_on_time_61_minutes_late
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1141", full_name="Quinn Reyes", booked_at="2026-05-01T00:00:00Z"
        )
        order, doses = fx.setup_dot_order_with_doses(
            inmate["id"],
            ["2026-05-01T08:00:00Z", "2026-05-01T12:00:00Z"],
            drug_name="Sertraline",
            drug_class="PSYCHOTROPIC",
            doses_per_day=2,
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-10T00:00:00Z",
        )
        fx.set_clock("2026-05-01T09:00:00Z")
        fx.record_dose(doses[0]["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})

        fx.set_clock("2026-05-01T13:01:00Z")
        second = fx.record_dose(
            doses[1]["id"], {"outcome": "ADMINISTERED", "observed_swallow": True}
        )
        assert second["timing_class"] == "LATE"

        order_now = fx.read_order(order["id"])
        assert_adherence_equals(order_now["adherence_pct"], 100.00)
        assert order_now["consecutive_missed_count"] == 0
