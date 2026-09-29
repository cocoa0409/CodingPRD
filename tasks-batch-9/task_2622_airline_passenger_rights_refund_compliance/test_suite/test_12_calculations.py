"""Threshold selection, rounding order and the ledger aggregates they feed."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_HEADERS,
    OPS_HEADERS,
    add_ancillary,
    add_checked_bag,
    acknowledge,
    answer,
    assert_booking_ledger,
    assert_cents,
    assert_exposure,
    assert_hours,
    assert_instant,
    assert_list_meta,
    assert_null,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_obligation_deadlines,
    assert_segment_state,
    booking_version,
    build_international_world,
    build_world,
    cancel_segment,
    elect,
    factories as f,
    file_complaint,
    obligations_with_meta,
    open_report,
    read_bag,
    read_booking,
    read_complaint,
    read_denied_boarding,
    read_exposure,
    read_obligation,
    read_passenger,
    read_profile,
    read_segment,
    read_tarmac_event,
    record_operation,
    sole_obligation,
    void,
)


class TestDeniedBoardingLadderFreeRung:
    def test_a_substitute_exactly_sixty_minutes_late_costs_nothing(self, api):
        """One hour is inclusive on the free rung, so the skip is counted, not a zero row.

        PRD §3.4: "The first rung is free: a substitute delay of at most 60 minutes — one
        hour, inclusive — carries a statutory compensation of 0."

        PRD §3.4: "When `compensation_cents` comes out as 0, because the substitute delay
        landed on the free rung, no obligation is written and the booking's
        `suppressed_obligation_count` increases by 1 instead."

        Design: Corner/calculations/denied_boarding_no_compensation_at_sixty_minute_boundary
        """
        world = build_world(api, total_fare_cents=60000, segment_fares=[60000])
        record = validate_success(
            api.create_denied_boarding_record(
                f.denied_boarding_payload(
                    world.booking["id"],
                    world.segments[0]["id"],
                    "INVOLUNTARY",
                    45000,
                    "2026-08-10T15:00:00Z",
                    oversale_confirmed=True,
                    written_disclosure_provided=True,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        validate_success(
            api.finalize_denied_boarding_record(
                record["id"], f.finalize_payload("2026-08-10T16:00:00Z"), OFFICER_HEADERS
            )
        )

        stored = read_denied_boarding(api, record["id"])
        assert stored["status"] == "FINALIZED"
        assert stored["effective_category"] == "INVOLUNTARY"
        assert stored["substitute_delay_minutes"] == 60
        assert_cents(
            stored["statutory_compensation_cents"], 0, "statutory_compensation_cents"
        )
        assert_cents(stored["compensation_cents"], 0, "compensation_cents")
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 0, False)
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=0,
            suppressed_obligation_count=1,
            disruption_posture="NORMAL",
        )


class TestComplaintAnswerWindowSelection:
    def test_a_disability_matter_answers_on_the_same_day_it_is_acknowledged(self, api):
        """The 30-day disability window replaces the 60-day general one.

        PRD §3.8: "`answer_due_utc` is the substantive-answer window added to
        `received_at_utc`, and here the category matters: a `DISABILITY` complaint gets the
        shortened disability window of 30 days by default, while every other category gets the
        general window of 60 days."

        PRD §3.8: "Under the defaults a disability matter's answer is therefore due at
        exactly the same instant its acknowledgement is, which is the point — accommodation
        failures cannot be parked."

        Design: Corner/calculations/disability_complaint_answer_window_uses_thirty_day_constant
        """
        world = build_world(api, total_fare_cents=50000, requires_disability_assistance=True)

        complaint = file_complaint(
            api,
            world.booking["id"],
            category="DISABILITY",
            channel="PHONE",
            received_at_utc="2026-08-05T09:00:00Z",
            summary="Wheelchair assistance was not provided at the gate.",
        )

        assert complaint["category"] == "DISABILITY"
        assert complaint["status"] == "RECEIVED"
        assert_instant(complaint["ack_due_utc"], "2026-09-04T09:00:00Z")
        assert_instant(complaint["answer_due_utc"], "2026-09-04T09:00:00Z")
        profile = read_profile(api, world.profile["id"])
        assert profile["complaint_answer_deadline_days_disability"] == 30
        assert profile["complaint_answer_deadline_days_general"] == 60


class TestBagDelayThresholdSelection:
    def test_an_international_itinerary_forgives_a_twenty_nine_hour_delivery(self, api):
        """The booking-level scope, not the leg, raises the bar to thirty hours.

        PRD §3.3: "That figure is compared against the bag-delay threshold that governs
        the itinerary — and here, unlike the significant-delay rule, it is the
        **booking-level** `itinerary_scope` that selects the threshold, because a bag travels
        the whole itinerary rather than one leg: the international figure when the scope reads
        `INTERNATIONAL`, the domestic figure otherwise."

        PRD §3.3: "When the delay falls short of the threshold, the bag moves `IN_TRANSIT →
        DELIVERED_ON_TIME`, `delivered_at_utc` and `delivery_delay_hours` are stored, the bag's
        `version` advances by 1, and no obligation is created."

        Design: Corner/calculations/international_itinerary_uses_thirty_hour_bag_threshold
        """
        world = build_international_world(api, total_fare_cents=90000, segment_fare_cents=90000)
        bag = add_checked_bag(
            api,
            world.booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T16:00:00Z",
            "2026-08-11T09:00:00Z",
        )

        validate_success(
            api.resolve_checked_bag(
                bag["id"], f.bag_delivered_payload("2026-08-12T14:00:00Z"), OFFICER_HEADERS
            )
        )

        booking = read_booking(api, world.booking["id"])
        assert_booking_ledger(booking, itinerary_scope="INTERNATIONAL")
        stored = read_bag(api, bag["id"], world.booking["id"])
        assert_hours(stored["delivery_delay_hours"], 29.0)
        assert stored["status"] == "DELIVERED_ON_TIME"
        assert stored["fee_refund_obligated"] is False
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 0, False)
        assert_booking_ledger(
            booking, total_refund_obligated_cents=0, collected_total_cents=94500
        )

    def test_eleven_hours_fifty_nine_minutes_rounds_just_under_the_domestic_limit(self, api):
        """11.98 hours fails an at-or-above comparison against 12.00.

        PRD §3.3: "On a `DELIVERED` resolution the system computes `delivery_delay_hours`
        as the difference between `delivered_at_utc` and `scheduled_delivery_utc`, taken from
        the raw second difference, converted to hours and rounded half up to two decimal
        places."

        PRD §3.3: "The comparison is at-or-above, so a bag delivered exactly 12.00 hours
        late on a default domestic itinerary is late."

        Design: Corner/calculations/bag_delay_just_below_domestic_threshold_stays_on_time
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])
        bag = add_checked_bag(
            api,
            world.booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T13:00:00Z",
            "2026-08-10T21:00:00Z",
        )

        validate_success(
            api.resolve_checked_bag(
                bag["id"], f.bag_delivered_payload("2026-08-11T08:59:00Z"), OFFICER_HEADERS
            )
        )

        booking = read_booking(api, world.booking["id"])
        assert_booking_ledger(booking, itinerary_scope="DOMESTIC")
        stored = read_bag(api, bag["id"], world.booking["id"])
        assert_hours(stored["delivery_delay_hours"], 11.98)
        assert stored["status"] == "DELIVERED_ON_TIME"
        assert stored["fee_refund_obligated"] is False
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 0, False)
        assert_null(booking["earliest_refund_deadline_utc"], "earliest_refund_deadline_utc")


class TestTravelCreditBonusRounding:
    def test_a_half_cent_bonus_product_rounds_up_and_stays_out_of_the_ledger(self, api):
        """80005 tenths is 8000.5, which rounds to 8001 without touching the obligated total.

        PRD §3.7: "Electing `TRAVEL_CREDIT` sets `election_status` to `ELECTED_CREDIT` and
        `settlement_method` to `TRAVEL_CREDIT`, and adds the goodwill bonus:
        `credit_bonus_cents` is the obligation's `amount_cents` multiplied by the profile's
        `travel_credit_election_bonus_pct` and rounded half up — one tenth of the principal
        under the regulatory default — and `payable_total_cents` becomes `amount_cents` plus
        that bonus."

        PRD §3.7: "The booking's `total_refund_obligated_cents` is deliberately **not**
        changed by the bonus: goodwill sits outside the obligated-money ledger and outside the
        consumed figure that headroom subtracts, so electing credit never shrinks the headroom
        available to obligations minted later."

        PRD §3.7: "A `Passenger` electing credit for themselves needs no such artefact —
        their own request is the consent."

        Design: Corner/calculations/travel_credit_bonus_rounds_half_up_on_odd_cent_product
        """
        world = build_world(api, total_fare_cents=80005, segment_fares=[80005])
        cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")
        obligation = sole_obligation(api, world.booking["id"])

        elect(api, obligation["id"], "TRAVEL_CREDIT", world.passenger_headers)

        elected = read_obligation(api, obligation["id"])
        assert_obligation_amounts(
            elected, amount_cents=80005, credit_bonus_cents=8001, payable_total_cents=88006
        )
        assert_obligation_axes(
            elected,
            election_status="ELECTED_CREDIT",
            election_source="PASSENGER",
            settlement_method="TRAVEL_CREDIT",
        )
        assert_null(elected["credit_consent_reference"], "credit_consent_reference")
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=80005
        )
        assert read_passenger(api, world.passenger["id"])["travel_credit_balance_cents"] == 0


class TestSettlementWindowByPaymentMethod:
    def test_a_cash_booking_gets_twenty_days_while_the_election_window_stays_at_five(
        self, api
    ):
        """The payment form stretches only the settlement clock, not the election clock.

        PRD §3.6: "From the start instant, `deadline_utc` is the settlement deadline: the
        number of days configured for credit-card payments when the booking's `payment_method`
        is `CREDIT_CARD`, and the number configured for every other form of payment otherwise —
        seven days against twenty days under the regulatory defaults, which is why the form of
        payment collected at booking time still matters months later."

        PRD §3.6: "And `election_deadline_utc` is five days after the start instant, this
        election window being a statutory constant the carrier cannot tune."

        Design: Corner/calculations/non_credit_card_payment_uses_twenty_day_refund_window
        """
        world = build_world(
            api,
            total_fare_cents=90000,
            payment_method="CASH_OR_CHECK",
            segment_fares=[90000],
        )

        cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")

        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 1, False)
        obligation = rows[0]
        assert obligation["basis"] == "FARE"
        assert_obligation_amounts(obligation, amount_cents=90000)
        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-10T10:00:00Z",
            deadline_utc="2026-08-30T10:00:00Z",
            election_deadline_utc="2026-08-15T10:00:00Z",
            deadline_breached=False,
        )
        booking = read_booking(api, world.booking["id"])
        assert_instant(booking["earliest_refund_deadline_utc"], "2026-08-30T10:00:00Z")


class TestInstrumentProjection:
    def test_a_credit_paid_ticket_cannot_be_laundered_into_cash(self, api):
        """A cash election on a credit-paid booking still settles as travel credit, unbonused.

        PRD §3.7: "Electing `CASH` sets `election_status` to `ELECTED_CASH`, leaves
        `credit_bonus_cents` at 0 and `payable_total_cents` equal to `amount_cents`, resolves
        the `settlement_method`, and advances the obligation's `version` by 1."

        PRD §3.7: "The instrument is a projection of how the ticket was paid for: a
        `CREDIT_CARD` booking resolves to `ORIGINAL_PAYMENT`, a `CASH_OR_CHECK` booking to
        `CASH_OR_CHECK`, a `MILES` booking to `MILES`, and a booking originally paid for in
        travel credit resolves back to `TRAVEL_CREDIT` even on a cash election — a passenger
        cannot launder credit into cash by electing cash."

        Design: Corner/calculations/travel_credit_booking_electing_cash_resolves_back_to_travel_credit
        """
        world = build_world(
            api,
            total_fare_cents=50000,
            payment_method="TRAVEL_CREDIT",
            segment_fares=[50000],
        )
        cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")
        obligation = sole_obligation(api, world.booking["id"])

        elect(api, obligation["id"], "CASH", world.passenger_headers)

        elected = read_obligation(api, obligation["id"])
        assert_obligation_axes(
            elected,
            election_status="ELECTED_CASH",
            election_source="PASSENGER",
            settlement_method="TRAVEL_CREDIT",
        )
        assert_obligation_amounts(
            elected, credit_bonus_cents=0, payable_total_cents=50000
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=50000
        )


class TestEarliestDeadlineAcrossBases:
    def test_two_bases_with_different_clock_origins_report_the_minimum_deadline(self, api):
        """The later-created baggage row does not displace the earlier ancillary deadline.

        PRD §2.11: "`earliest_refund_deadline_utc`, the smallest `deadline_utc` among the
        booking's obligations whose settlement axis is neither settled nor voided, null when
        that set is empty, with ties resolved by `created_at` ascending and never by `id`"

        PRD §2.11: "A booking's `total_refund_obligated_cents` must always equal the sum of
        `amount_cents` over that booking's refund obligations whose settlement axis is anything
        other than voided, summed in `created_at` ascending order."

        Design: Corner/calculations/earliest_refund_deadline_aggregates_minimum_across_bases
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[90000])
        extra = add_ancillary(
            api, world.booking["id"], world.segments[0]["id"], "SEAT_SELECTION", 5000
        )
        bag = add_checked_bag(
            api,
            world.booking["id"],
            "BAG0000001",
            4500,
            "2026-08-10T13:00:00Z",
            "2026-08-10T21:00:00Z",
        )
        validate_success(
            api.mark_ancillary_not_provided(
                extra["id"],
                f.not_provided_payload("EQUIPMENT_SWAP", "2026-08-09T08:00:00Z"),
                OFFICER_HEADERS,
            )
        )

        validate_success(
            api.resolve_checked_bag(
                bag["id"], f.bag_delivered_payload("2026-08-11T09:00:00Z"), OFFICER_HEADERS
            )
        )

        stored_bag = read_bag(api, bag["id"], world.booking["id"])
        assert_hours(stored_bag["delivery_delay_hours"], 12.0)
        assert stored_bag["status"] == "DELIVERED_LATE"
        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 2, False)
        by_basis = {row["basis"]: row for row in rows}
        assert_obligation_amounts(by_basis["ANCILLARY"], amount_cents=5000)
        assert_obligation_deadlines(
            by_basis["ANCILLARY"],
            obligation_start_utc="2026-08-09T08:00:00Z",
            deadline_utc="2026-08-16T08:00:00Z",
        )
        assert_obligation_amounts(by_basis["BAGGAGE_FEE"], amount_cents=4500)
        assert_obligation_deadlines(
            by_basis["BAGGAGE_FEE"],
            obligation_start_utc="2026-08-11T09:00:00Z",
            deadline_utc="2026-08-18T09:00:00Z",
        )
        booking = read_booking(api, world.booking["id"])
        assert_booking_ledger(
            booking, total_refund_obligated_cents=9500, collected_total_cents=99500
        )
        assert_instant(booking["earliest_refund_deadline_utc"], "2026-08-16T08:00:00Z")


class TestTarmacMinuteAccounting:
    def test_an_open_occupation_adds_no_minutes_to_the_legs_running_total(self, api):
        """The touching second event is accepted yet contributes nothing until it closes.

        PRD §3.5: "The event moves `DELAY_ACTIVE → DEPLANED`, its `interval_end_utc` is set
        to the deplaning instant, its `tarmac_minutes` becomes the difference between
        `interval_end_utc` and `tarmac_start_utc` in whole minutes with the remainder dropped,
        and `is_violation` becomes true when `tarmac_minutes` is **strictly greater** than the
        event's `deadline_minutes` — occupying the tarmac for exactly the deadline is
        compliant."

        PRD §3.5: "A new event begins in `DELAY_ACTIVE` with `interval_end_utc` null,
        `tarmac_minutes` at 0 and `is_violation` false, and — importantly — with its
        `deadline_minutes` resolved and frozen at creation time from the leg's `is_international`
        flag and the booking's pinned policy profile: the international deplaning deadline for an
        international leg, the domestic one otherwise."

        Design: Corner/calculations/delay_active_tarmac_event_contributes_no_minutes_to_segment_total
        """
        world = build_world(api, total_fare_cents=50000, segment_fares=[50000])
        segment_id = world.segments[0]["id"]
        first = validate_success(
            api.create_tarmac_delay_event(
                f.tarmac_event_payload(segment_id, "2026-08-10T12:00:00Z", "DEPARTURE"),
                OPS_HEADERS,
            ),
            201,
        )
        validate_success(
            api.deplane_tarmac_event(
                first["id"], f.deplane_payload("2026-08-10T13:00:00Z"), OPS_HEADERS
            )
        )

        second = validate_success(
            api.create_tarmac_delay_event(
                f.tarmac_event_payload(segment_id, "2026-08-10T13:00:00Z", "DEPARTURE"),
                OPS_HEADERS,
            ),
            201,
        )

        closed = read_tarmac_event(api, first["id"], segment_id)
        assert closed["status"] == "DEPLANED"
        assert closed["tarmac_minutes"] == 60
        assert closed["is_violation"] is False
        still_open = read_tarmac_event(api, second["id"], segment_id)
        assert still_open["status"] == "DELAY_ACTIVE"
        assert still_open["tarmac_minutes"] == 0
        assert_null(still_open["interval_end_utc"], "interval_end_utc")
        assert_segment_state(
            read_segment(api, segment_id),
            cumulative_tarmac_minutes=60,
            exempted_tarmac_event_count=0,
        )


class TestCascadeVariantSelection:
    def test_the_cascade_values_the_unflown_leg_rather_than_prorating(self, api):
        """60000 of remaining itinerary, not the 45000 an even split would have produced.

        PRD §3.2: "**Link three-a,** caused by link one: one refund obligation on a `FARE`
        basis in proactive issuance mode, naming the cancelled leg, is minted per the proactive
        full-itinerary valuation and clamped to the booking's remaining headroom; if the clamp
        yields zero the obligation is skipped and the booking's `suppressed_obligation_count`
        increases by 1 instead."

        PRD §3.6: "In proactive mode the variant is `PROACTIVE_FULL_ITINERARY`: when the
        booking's `travel_commenced` is false, `gross_entitlement_cents` is the booking's whole
        `total_fare_cents`; when travel has commenced, it is the sum of `segment_fare_cents`
        over the booking's legs whose `status` is `SCHEDULED`, `DELAYED`, `CANCELLED` or
        `DISRUPTED_UNUSED`, added in ascending `sequence_index` order with no intermediate
        rounding since each per-leg fare is already whole cents."

        PRD §3.6: "This variant values the remaining itinerary and never prorates by leg
        count."

        Design: Corner/calculations/cascade_always_selects_proactive_full_itinerary_variant
        """
        world = build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])
        record_operation(api, world.segments[0]["id"], "DEPARTED", "2026-08-10T12:05:00Z")
        record_operation(api, world.segments[0]["id"], "ARRIVED", "2026-08-10T13:55:00Z")

        cancel_segment(api, world.segments[1]["id"], "2026-08-10T15:00:00Z")

        rows, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, 1, False)
        obligation = rows[0]
        assert obligation["issuance_mode"] == "PROACTIVE"
        assert obligation["variant_applied"] == "PROACTIVE_FULL_ITINERARY"
        assert_obligation_amounts(
            obligation, gross_entitlement_cents=60000, amount_cents=60000
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            travel_commenced=True,
            unused_segment_count=1,
            total_refund_obligated_cents=60000,
        )


class TestHeadroomInputSet:
    def test_statutory_compensation_and_voided_rows_stay_out_of_the_headroom(self, api):
        """77500 of denied-boarding money leaves the full 60000 fare still available.

        PRD §3.6: "The money already consumed is the sum of `amount_cents` over the
        booking's obligations whose settlement axis is not voided **and** whose `basis` is not
        `DENIED_BOARDING`, added in ascending `created_at` order; statutory denied-boarding
        compensation is excluded because it compensates a service failure rather than refunding
        money collected."

        PRD §3.6: "`remaining_headroom_cents`, computed exactly as step two above"

        PRD §3.7: "A void sets the settlement axis to `VOIDED`, stores the `void_reason`,
        advances the obligation's `version` by 1, and recomputes the booking's
        `total_refund_obligated_cents` (now excluding this row), `earliest_refund_deadline_utc`
        and `disruption_posture`, advancing the booking's `version` by 1 — restoring the
        conserved ledger of §2.11 exactly."

        Design: Corner/calculations/headroom_input_set_excludes_denied_boarding_and_voided_obligations
        """
        world = build_world(api, total_fare_cents=60000, segment_fares=[60000])
        record = validate_success(
            api.create_denied_boarding_record(
                f.denied_boarding_payload(
                    world.booking["id"],
                    world.segments[0]["id"],
                    "INVOLUNTARY",
                    45000,
                    "2026-08-10T15:30:00Z",
                    oversale_confirmed=True,
                    written_disclosure_provided=True,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        validate_success(
            api.finalize_denied_boarding_record(
                record["id"], f.finalize_payload("2026-08-10T16:00:00Z"), OFFICER_HEADERS
            )
        )

        fare_obligation = validate_success(
            api.create_refund_obligation(
                f.obligation_payload(
                    world.booking["id"],
                    booking_version(api, world.booking["id"]),
                    "FARE",
                    "PROACTIVE",
                    flight_segment_id=world.segments[0]["id"],
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert_obligation_amounts(
            fare_obligation, headroom_at_creation_cents=60000, amount_cents=60000
        )
        void(api, fare_obligation["id"], "CREATED_IN_ERROR")

        voided = read_obligation(api, fare_obligation["id"])
        assert_obligation_axes(voided, settlement_status="VOIDED")
        assert voided["void_reason"] == "CREATED_IN_ERROR"
        assert_exposure(
            read_exposure(api, world.booking["id"]),
            obligated_total_cents=77500,
            remaining_headroom_cents=60000,
            collected_total_cents=60000,
        )
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=77500
        )


class TestReportWindowInclusivity:
    def test_the_final_second_of_the_period_counts_and_the_next_second_does_not(self, api):
        """One complaint lands inside the closed window; the one a second later is invisible.

        PRD §3.9: "The scope is every booking pinned to the report's profile and the rows
        hanging off those bookings, and the window is closed on both ends — a row counts when
        its own domain timestamp is at or after `period_start_utc` and at or before
        `period_end_utc`, and it is always the domain timestamp that is tested, never
        `created_at`."

        PRD §3.9: "Every consumer complaint inside the report's scope and period must have
        reached `ANSWERED` or `CLOSED`; an open complaint anywhere in the window blocks the
        filing with `ERR_OPEN_COMPLAINT_IN_PERIOD`."

        Design: Corner/calculations/regulator_metrics_closed_window_includes_the_period_end_instant
        """
        world = build_world(api, total_fare_cents=50000)
        in_window = file_complaint(
            api,
            world.booking["id"],
            category="REFUND",
            channel="EMAIL",
            received_at_utc="2026-08-31T23:59:59Z",
            summary="In-window complaint.",
        )
        acknowledge(api, in_window["id"], "2026-09-01T00:00:00Z")
        answer(api, in_window["id"], "2026-09-01T01:00:00Z", "POLICY_EXPLAINED")
        out_of_window = file_complaint(
            api,
            world.booking["id"],
            category="BAGGAGE",
            channel="EMAIL",
            received_at_utc="2026-09-01T00:00:00Z",
            summary="Out-of-window complaint.",
        )
        report = open_report(
            api, world.profile["id"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"
        )

        submitted = validate_success(
            api.submit_regulator_report(
                report["id"], f.submit_report_payload("2026-09-02T00:00:00Z"), ADMIN_HEADERS
            )
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["complaint_count"] == 1
        assert submitted["disability_complaint_count"] == 0
        assert submitted["late_answer_count"] == 0
        assert submitted["tarmac_violation_count"] == 0
        assert submitted["involuntary_denied_boarding_count"] == 0
        assert submitted["refund_obligation_cents_total"] == 0
        assert submitted["overdue_refund_count"] == 0
        assert submitted["policy_version_pinned"] == 2
        assert read_complaint(api, out_of_window["id"])["status"] == "RECEIVED"
