"""Prescribing under inmate-version concurrency, the closed date span, the two adherence
variants, the hold/resume compensating pair and the facility adherence index."""

from test_helpers import (
    ApiErrorId,
    assert_adherence_equals,
    assert_dose_partition,
    assert_medication_order,
    assert_same_instant,
    fixtures as fx,
    medication_order_payload,
    validate_error,
    validate_success,
)


class TestOrderCreateInitialisation:
    def test_create_initialises_server_owned_fields_from_the_acting_prescriber(
        self, api, provider_headers
    ):
        """PRD §3.4: "A surviving create initializes `status` to `ACTIVE`, sets
        `prescriber_user_id` to the acting `X-User-ID`, zeroes `units_dispensed`,
        `units_returned`, `consecutive_missed_count` and `consecutive_refused_count`, sets
        `adherence_pct` to 0.00, and sets both `escalated_to_prescriber` and `forced_dot` to
        false. The inmate's `version` increments by 1, which means every successful order
        write invalidates any other client's cached inmate version."

        Design: Corner/entities/computed_fields_reject_client_supplied_values
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2030", full_name="Ula Vance", booked_at="2026-05-01T00:00:00Z"
        )
        headers = dict(provider_headers)
        headers["X-User-ID"] = "u-prov-77"
        resp = api.create_medication_order(
            medication_order_payload(inmate["id"], inmate["version"]), headers
        )
        data = validate_success(resp, 201)
        assert_medication_order(data)
        assert_adherence_equals(data["adherence_pct"], 0.00)
        assert data["prescriber_user_id"] == "u-prov-77"
        assert data["status"] == "ACTIVE"
        assert data["units_dispensed"] == 0
        assert data["units_returned"] == 0
        assert fx.read_inmate(inmate["id"])["version"] == 2

    def test_stale_expected_inmate_version_is_rejected_and_a_refreshed_read_succeeds(
        self, api, provider_headers
    ):
        """PRD §2.7: "Writing a medication order — the create that a `Provider` issues
        against `POST /medication-orders` — requires the body field
        `expected_inmate_version`, carrying the `version` integer of the target inmate as the
        client last observed it. This field is not optional. If it does not equal the
        inmate's current `version`, the create is rejected with `ERR_STALE_INMATE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_inmate_version_rejected_on_medication_order
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2380", full_name="Fin Iqbal", booked_at="2026-05-01T00:00:00Z"
        )
        stale_version = inmate["version"]
        first = fx.write_medication_order(
            inmate["id"], drug_name="Sertraline", drug_class="PSYCHOTROPIC"
        )

        second_payload = medication_order_payload(
            inmate["id"],
            stale_version,
            drug_name="Lisinopril",
            drug_class="CHRONIC_MAINTENANCE",
        )
        resp = api.create_medication_order(second_payload, provider_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_INMATE_VERSION.value, 412)

        fresh_version = fx.inmate_version(inmate["id"])
        second_payload["expected_inmate_version"] = fresh_version
        retry = api.create_medication_order(second_payload, provider_headers)
        second = validate_success(retry, 201)

        assert fx.read_inmate(inmate["id"])["version"] == 3
        assert fx.read_order(first["id"])["status"] == "ACTIVE"
        assert fx.read_order(second["id"])["status"] == "ACTIVE"


class TestClosedDateSpanCollision:
    def test_new_order_sharing_one_endpoint_date_collides(self, api, provider_headers):
        """PRD §3.4: "Two orders collide when they belong to the same inmate, share a
        `drug_class`, carry *different* `drug_name` values, the existing one is `ACTIVE`, and
        their calendar-date spans intersect — where each order's span runs from its
        `start_date` calendar date to its `end_date` calendar date as a **closed** interval
        on both ends. Two orders that share exactly one endpoint date, so that the new order
        begins on the day the existing order ends, therefore **do** collide; starting one day
        later does not. A collision is rejected with `ERR_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/medication_order_closed_date_span_collision
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1200", full_name="Yuri Zane", booked_at="2026-05-01T00:00:00Z"
        )
        incumbent = fx.write_medication_order(
            inmate["id"],
            drug_name="Lisinopril",
            drug_class="CHRONIC_MAINTENANCE",
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-10T00:00:00Z",
        )
        version = fx.inmate_version(inmate["id"])

        resp = api.create_medication_order(
            medication_order_payload(
                inmate["id"],
                version,
                drug_name="Amlodipine",
                drug_class="CHRONIC_MAINTENANCE",
                start_date="2026-05-10T00:00:00Z",
                end_date="2026-05-20T00:00:00Z",
            ),
            provider_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)
        assert fx.read_order(incumbent["id"])["status"] == "ACTIVE"

    def test_new_order_starting_one_day_later_clears_the_closed_span(self, api, provider_headers):
        """PRD §3.4: "Two orders collide when they belong to the same inmate, share a
        `drug_class`, carry *different* `drug_name` values, the existing one is `ACTIVE`, and
        their calendar-date spans intersect — where each order's span runs from its
        `start_date` calendar date to its `end_date` calendar date as a **closed** interval
        on both ends. Two orders that share exactly one endpoint date, so that the new order
        begins on the day the existing order ends, therefore **do** collide; starting one day
        later does not. A collision is rejected with `ERR_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/medication_order_closed_date_span_collision
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1201", full_name="Yuri Zane", booked_at="2026-05-01T00:00:00Z"
        )
        incumbent = fx.write_medication_order(
            inmate["id"],
            drug_name="Lisinopril",
            drug_class="CHRONIC_MAINTENANCE",
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-10T00:00:00Z",
        )
        version = fx.inmate_version(inmate["id"])

        resp = api.create_medication_order(
            medication_order_payload(
                inmate["id"],
                version,
                drug_name="Amlodipine",
                drug_class="CHRONIC_MAINTENANCE",
                start_date="2026-05-11T00:00:00Z",
                end_date="2026-05-20T00:00:00Z",
            ),
            provider_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE"
        assert_same_instant(data["start_date"], "2026-05-11T00:00:00Z", "start_date")
        assert fx.read_order(incumbent["id"])["status"] == "ACTIVE"


class TestAdherenceVariants:
    def test_directly_observed_variant_scores_events_over_the_scored_denominator(self, api):
        """PRD §3.4: "- **The directly-observed variant** counts events. The denominator is
        the number of administration rows under the order whose outcome is `ADMINISTERED`,
        `REFUSED` or `MISSED`; rows still `SCHEDULED` and rows `VOIDED` are excluded from
        both numerator and denominator. If that denominator is zero, `adherence_pct` is
        exactly 0.00. Otherwise the numerator is the number of those rows whose outcome is
        `ADMINISTERED` **and** whose `timing_class` is either `ON_TIME` or `LATE` — an
        administered dose classified `MISSED_WINDOW` counts against the order in the
        denominator while contributing nothing to the numerator. The percentage is one
        hundred times the numerator divided by the denominator, rounded half up to 2 decimal
        places."

        Design: Difficulty/dual_variant_calc/medication_adherence_dot_vs_kop_denominator
        """
        scenario = fx.setup_dot_and_kop_orders_for_one_patient()
        dot_order = scenario["dot_order"]

        on_time = fx.read_administration(dot_order["id"], scenario["dose_on_time"]["id"])
        late = fx.read_administration(dot_order["id"], scenario["dose_late"]["id"])
        missed = fx.read_administration(dot_order["id"], scenario["dose_missed"]["id"])
        assert on_time["timing_class"] == "ON_TIME"
        assert late["timing_class"] == "LATE"
        assert missed["timing_class"] == "MISSED_WINDOW"

        assert_adherence_equals(fx.read_order(dot_order["id"])["adherence_pct"], 66.67)

    def test_keep_on_person_variant_scores_pills_against_the_expected_unit_count(self, api):
        """PRD §3.4: "- **The keep-on-person variant** counts pills against time. The last
        day of the measured span is the earlier of the current clock's calendar date and the
        order's `end_date` calendar date. If that last day precedes the order's `start_date`
        calendar date, the expected unit count is zero. Otherwise the expected unit count is
        `doses_per_day` multiplied by the number of whole days from `start_date`'s calendar
        date to that last day, **plus one**, because the span is inclusive of both endpoints
        — a one-day order at two doses per day expects two units, not zero. With an expected
        count of zero, `adherence_pct` is exactly 0.00. Otherwise consumption is
        `units_dispensed` minus `units_returned`, the raw percentage is one hundred times
        consumption divided by the expected count, and the result is clamped into the range 0
        through 100 inclusive before being rounded half up to 2 decimal places."
        PRD §3.4: "A `Nurse` feeds the keep-on-person variant by recording pill counts,
        supplying `units_dispensed_delta` and `units_returned_delta`, which are added to the
        order's running `units_dispensed` and `units_returned` totals before adherence is
        recomputed and the order's `version` incremented by 1."

        Design: Difficulty/dual_variant_calc/medication_adherence_dot_vs_kop_denominator
        """
        scenario = fx.setup_dot_and_kop_orders_for_one_patient()
        kop_order = scenario["kop_order"]

        updated = validate_success(
            api.record_pill_count(
                kop_order["id"],
                {"units_dispensed_delta": 4, "units_returned_delta": 2},
                fx.NURSE,
            ),
            200,
        )
        assert updated["units_dispensed"] == 4
        assert updated["units_returned"] == 2
        assert_adherence_equals(updated["adherence_pct"], 50.00)
        assert_adherence_equals(fx.read_order(kop_order["id"])["adherence_pct"], 50.00)


class TestHoldResumeConservation:
    def test_hold_and_resume_leave_the_five_outcome_buckets_untouched(self, api):
        """PRD §2.9: "**The dose-count invariant.** For every medication order, the five
        outcome buckets `SCHEDULED`, `ADMINISTERED`, `REFUSED`, `MISSED` and `VOIDED`
        partition that order's administration rows exactly: the sum of the five bucket counts
        always equals the total number of administration rows created under the order, with
        no row double-counted and none dropped."

        Design: Difficulty/compensating_invariant/hold_resume_conserves_dose_partition_and_counters
        """
        scenario = fx.setup_order_with_mixed_dose_outcomes()
        order_id = scenario["order"]["id"]
        before = fx.administrations_for(order_id)
        buckets_before = assert_dose_partition(before, 4)

        fx.hold_order(order_id)
        fx.resume_order(order_id)

        after = fx.administrations_for(order_id)
        buckets_after = assert_dose_partition(after, 4)
        assert buckets_after == buckets_before
        assert buckets_after["VOIDED"] == 0
        assert fx.read_order(order_id)["status"] == "ACTIVE"

    def test_hold_and_resume_preserve_the_consecutive_counters_and_adherence(self, api):
        """PRD §3.4: "A hold is a pure gate and nothing more: doses already scheduled in the
        future stay `SCHEDULED` and are simply blocked from being acted on while the hold is
        in force, `adherence_pct` is not recomputed in either direction, and
        `consecutive_missed_count` and `consecutive_refused_count` are preserved across the
        hold with no reset."
        PRD §2.9: "The compensating pair here is holding an order followed by resuming it.
        After both have run, every bucket count is identical to its pre-hold value, and
        `consecutive_missed_count` and `consecutive_refused_count` are likewise unchanged."

        Design: Difficulty/compensating_invariant/hold_resume_conserves_dose_partition_and_counters
        """
        scenario = fx.setup_order_with_mixed_dose_outcomes()
        order_id = scenario["order"]["id"]
        before = fx.read_order(order_id)
        assert before["consecutive_refused_count"] == 1
        assert before["consecutive_missed_count"] == 1
        assert_adherence_equals(before["adherence_pct"], 33.33)

        fx.hold_order(order_id)
        fx.resume_order(order_id)

        after = fx.read_order(order_id)
        assert after["status"] == "ACTIVE"
        assert after["consecutive_refused_count"] == 1
        assert after["consecutive_missed_count"] == 1
        assert after["escalated_to_prescriber"] is False
        assert_adherence_equals(after["adherence_pct"], 33.33)

        outcomes = {row["id"]: row["outcome"] for row in fx.administrations_for(order_id)}
        doses = scenario["doses"]
        assert outcomes[doses[0]["id"]] == "ADMINISTERED"
        assert outcomes[doses[1]["id"]] == "REFUSED"
        assert outcomes[doses[2]["id"]] == "MISSED"
        assert outcomes[doses[3]["id"]] == "SCHEDULED"


class TestFacilityAdherenceIndex:
    def test_per_order_rounding_happens_before_the_average(self, api, admin_headers):
        """PRD §3.4: "Otherwise the rounding order is pinned and must not be optimized away:
        each order's `adherence_pct` is **already** rounded to 2 decimal places by the
        per-order formula above, those already-rounded values are summed, the sum is divided
        by the number of candidate orders, and the quotient is rounded half up to 2 decimal
        places one further time. Pooling raw numerators and denominators across orders and
        rounding only at the end produces a different number and is wrong."

        Design: Difficulty/combinatorial_formula/facility_adherence_round_per_order_then_average
        """
        scenario = fx.setup_three_orders_at_one_facility()
        assert_adherence_equals(fx.read_order(scenario["order_a"]["id"])["adherence_pct"], 33.33)
        assert_adherence_equals(fx.read_order(scenario["order_b"]["id"])["adherence_pct"], 100.00)
        assert_adherence_equals(fx.read_order(scenario["order_c"]["id"])["adherence_pct"], 100.00)

        data = validate_success(api.get_facility_adherence("FAC-01", admin_headers), 200)
        assert data["order_count"] == 3
        assert float(data["adherence_index"]) == 77.78, (
            "Pooling 3 administered over 5 scored events would have produced 60.00"
        )

    def test_report_body_names_the_facility_and_its_candidate_order_count(self, api, admin_headers):
        """PRD §3.4: "The candidate set is every medication order whose owning inmate's
        `facility_code` matches the requested code and whose status is `ACTIVE` or `HELD`,
        taken in `created_at` ascending order; discontinued and completed orders are excluded
        entirely."
        PRD §3.4: "The response body is a single object carrying the `facility_code` that was
        requested, the `order_count` of candidate orders, and the resulting
        `adherence_index`."

        Design: Difficulty/combinatorial_formula/facility_adherence_round_per_order_then_average
        """
        scenario = fx.setup_three_orders_at_one_facility()
        data = validate_success(api.get_facility_adherence("FAC-01", admin_headers), 200)
        assert data["facility_code"] == "FAC-01"
        assert data["order_count"] == 3
        assert float(data["adherence_index"]) == 77.78

        assert fx.read_order(scenario["order_a"]["id"])["status"] == "ACTIVE"
        assert fx.read_order(scenario["order_b"]["id"])["status"] == "ACTIVE"
        assert fx.read_order(scenario["order_c"]["id"])["status"] == "ACTIVE"

    def test_empty_candidate_set_yields_an_index_of_zero(self, api, admin_headers):
        """PRD §3.4: "At least 1 candidate order is required to produce a real index; when
        the candidate count falls below that — that is, when the set is empty — the index is
        exactly 0.00 and the call still succeeds, since an empty facility is not an error."

        Design: Difficulty/boundary_precision_check/facility_adherence_empty_candidate_set_returns_zero
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1160",
            full_name="Tay Uhl",
            facility_code="FAC-02",
            custody_level="MINIMUM",
            booked_at="2026-05-01T00:00:00Z",
        )
        order = fx.write_medication_order(inmate["id"])
        validate_success(api.discontinue_medication_order(order["id"], fx.PROVIDER), 200)

        resp = api.get_facility_adherence("FAC-02", admin_headers)
        assert resp.status_code == 200, "An empty facility is not an error"
        data = validate_success(resp, 200)
        assert data["order_count"] == 0
        assert float(data["adherence_index"]) == 0.00

    def test_discontinued_orders_leave_the_candidate_set(self, api, admin_headers):
        """PRD §3.4: "The candidate set is every medication order whose owning inmate's
        `facility_code` matches the requested code and whose status is `ACTIVE` or `HELD`,
        taken in `created_at` ascending order; discontinued and completed orders are excluded
        entirely."
        PRD §3.4: "Discontinuing an order moves it from `ACTIVE` or `HELD` to
        `DISCONTINUED`."

        Design: Difficulty/boundary_precision_check/facility_adherence_empty_candidate_set_returns_zero
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1161",
            full_name="Tay Uhl",
            facility_code="FAC-02",
            custody_level="MINIMUM",
            booked_at="2026-05-01T00:00:00Z",
        )
        order = fx.write_medication_order(inmate["id"])
        before = validate_success(api.get_facility_adherence("FAC-02", admin_headers), 200)
        assert before["order_count"] == 1

        validate_success(api.discontinue_medication_order(order["id"], fx.PROVIDER), 200)
        assert fx.read_order(order["id"])["status"] == "DISCONTINUED"

        after = validate_success(api.get_facility_adherence("FAC-02", admin_headers), 200)
        assert after["order_count"] == 0
        assert float(after["adherence_index"]) == 0.00
