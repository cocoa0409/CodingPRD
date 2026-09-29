"""Thresholds tested one unit either side, plus the empty-itinerary guard."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    OFFICER_HEADERS,
    OPS_HEADERS,
    assert_booking_ledger,
    assert_exposure,
    assert_obligation_deadlines,
    assert_segment_state,
    create_booking,
    create_passenger,
    create_policy_profile,
    delay_segment,
    factories as f,
    obligations_with_meta,
    read_booking,
    read_exposure,
    read_segment,
    read_tarmac_event,
    set_clock,
)


def _two_leg_booking(api, clock, record_locator, email, fare, leg_fare, leg_date="2026-08-12"):
    set_clock(api, clock)
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, email, "Bo Boundary")
    booking = create_booking(
        api, passenger["id"], profile["id"], record_locator, fare, "CREDIT_CARD"
    )
    legs = [
        (1, "ZQ101", "LAX", "DEN", f"{leg_date}T14:00:00Z", f"{leg_date}T17:00:00Z"),
        (2, "ZQ202", "DEN", "ORD", f"{leg_date}T18:30:00Z", f"{leg_date}T21:00:00Z"),
    ]
    segments = []
    for index, number, origin, destination, departure, arrival in legs:
        segments.append(
            validate_success(
                api.create_flight_segment(
                    booking["id"],
                    f.flight_segment_payload(
                        sequence_index=index,
                        flight_number=number,
                        origin_iata=origin,
                        destination_iata=destination,
                        scheduled_departure_utc=departure,
                        scheduled_arrival_utc=arrival,
                        segment_fare_cents=leg_fare,
                    ),
                    OPS_HEADERS,
                ),
                201,
            )
        )
    return profile, booking, segments


# ─── The three-hour significant-delay threshold ───────


def _delays_either_side_of_the_threshold(api):
    """179 minutes on the first leg, 180 on the second, both declared at 09:00."""
    _, booking, segments = _two_leg_booking(
        api, "2026-08-11T09:00:00Z", "SIG001", "significant@example.com", 100000, 50000
    )
    delay_segment(api, segments[0]["id"], "2026-08-12T19:59:00Z", "2026-08-11T09:00:00Z")
    delay_segment(api, segments[1]["id"], "2026-08-13T00:00:00Z", "2026-08-11T09:00:00Z")
    return booking, segments


class TestSignificantDelayThresholdInclusive:
    def test_one_minute_short_of_three_hours_is_not_a_significant_delay(self, api):
        """179 minutes leaves the leg delayed but costs the carrier nothing.

        PRD §3.2: "`is_significant_delay` is then true when `delay_minutes` is at or
        above the threshold that governs this leg — the international threshold from the
        pinned policy profile when the leg's own `is_international` flag is true, and the
        domestic threshold otherwise."

        PRD §3.2: "When `is_significant_delay` comes out false, no obligation is created;
        the booking's `disruption_posture` is still recomputed — reaching `DISRUPTED` when
        the booking has no obligations at all — and the booking's `version` still advances
        by 1."

        Design: Difficulty/boundary_precision_check/significant_delay_threshold_inclusive_at_180_minutes
        """
        _, segments = _delays_either_side_of_the_threshold(api)

        assert_segment_state(
            read_segment(api, segments[0]["id"]),
            status="DELAYED",
            disruption_type="DELAY",
            delay_minutes=179,
            is_significant_delay=False,
        )

    def test_exactly_three_hours_is_significant_and_mints_the_fare_obligation(self, api):
        """180 minutes crosses the inclusive threshold and values the whole itinerary.

        PRD §3.2: "When `is_significant_delay` becomes true and no non-voided fare
        obligation already points at this leg, the declaration mints one refund
        obligation for the leg on a `FARE` basis in proactive issuance mode, valued by the
        proactive full-itinerary rule of §3.6, and then recomputes the booking's ledger
        fields and advances the booking's `version` by 1."

        Design: Difficulty/boundary_precision_check/significant_delay_threshold_inclusive_at_180_minutes
        """
        booking, segments = _delays_either_side_of_the_threshold(api)

        assert_segment_state(
            read_segment(api, segments[1]["id"]),
            status="DELAYED",
            disruption_type="DELAY",
            delay_minutes=180,
            is_significant_delay=True,
        )
        rows, meta = obligations_with_meta(api, booking["id"], basis="FARE")
        assert meta["total_count"] == 1, "only the leg that crossed the line owes money"
        obligation = rows[0]
        assert obligation["flight_segment_id"] == segments[1]["id"]
        assert obligation["amount_cents"] == 100000
        assert obligation["variant_applied"] == "PROACTIVE_FULL_ITINERARY"
        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-11T09:00:00Z",
            deadline_utc="2026-08-18T09:00:00Z",
        )
        assert_booking_ledger(
            read_booking(api, booking["id"]),
            total_refund_obligated_cents=100000,
            disruption_posture="REFUND_OBLIGATED",
        )


# ─── The three-hour deplaning deadline ────────────────


def _occupations_either_side_of_the_deadline(api):
    """Exactly 180 tarmac minutes on one leg, 181 on the other."""
    _, booking, segments = _two_leg_booking(
        api,
        "2026-08-10T22:00:00Z",
        "TMC001",
        "deadline@example.com",
        60000,
        30000,
        leg_date="2026-08-10",
    )
    compliant = validate_success(
        api.create_tarmac_delay_event(
            f.tarmac_event_payload(segments[0]["id"], "2026-08-10T14:10:00Z", "DEPARTURE"),
            OPS_HEADERS,
        ),
        201,
    )
    violating = validate_success(
        api.create_tarmac_delay_event(
            f.tarmac_event_payload(segments[1]["id"], "2026-08-10T18:40:00Z", "DEPARTURE"),
            OPS_HEADERS,
        ),
        201,
    )
    validate_success(
        api.deplane_tarmac_event(
            compliant["id"], f.deplane_payload("2026-08-10T17:10:00Z"), OPS_HEADERS
        )
    )
    validate_success(
        api.deplane_tarmac_event(
            violating["id"], f.deplane_payload("2026-08-10T21:41:00Z"), OPS_HEADERS
        )
    )
    return segments, compliant, violating


class TestTarmacDeadlineStrict:
    def test_occupying_the_tarmac_for_exactly_the_deadline_is_compliant(self, api):
        """180 minutes against a 180-minute deadline is not a violation.

        PRD §3.5: "The event moves `DELAY_ACTIVE → DEPLANED`, its `interval_end_utc` is
        set to the deplaning instant, its `tarmac_minutes` becomes the difference between
        `interval_end_utc` and `tarmac_start_utc` in whole minutes with the remainder
        dropped, and `is_violation` becomes true when `tarmac_minutes` is **strictly
        greater** than the event's `deadline_minutes` — occupying the tarmac for exactly
        the deadline is compliant."

        Design: Difficulty/boundary_precision_check/tarmac_deadline_strict_at_180_minutes
        """
        segments, compliant, _ = _occupations_either_side_of_the_deadline(api)

        event = read_tarmac_event(api, compliant["id"], segments[0]["id"])

        assert event["status"] == "DEPLANED"
        assert event["tarmac_minutes"] == 180
        assert event["deadline_minutes"] == 180
        assert event["is_violation"] is False
        assert_segment_state(
            read_segment(api, segments[0]["id"]), cumulative_tarmac_minutes=180
        )

    def test_one_minute_past_the_deadline_is_a_violation(self, api):
        """181 minutes trips the strict comparison and lands on the leg's clock too.

        PRD §3.5: "The event's `version` advances by 1, the leg's
        `cumulative_tarmac_minutes` grows by the event's `tarmac_minutes`, and the leg's
        `version` advances by 1."

        Design: Difficulty/boundary_precision_check/tarmac_deadline_strict_at_180_minutes
        """
        segments, _, violating = _occupations_either_side_of_the_deadline(api)

        event = read_tarmac_event(api, violating["id"], segments[1]["id"])

        assert event["status"] == "DEPLANED"
        assert event["tarmac_minutes"] == 181
        assert event["deadline_minutes"] == 180
        assert event["is_violation"] is True
        assert_segment_state(
            read_segment(api, segments[1]["id"]), cumulative_tarmac_minutes=181
        )


# ─── The zero-segment exposure guard ──────────────────


def _booking_without_legs(api):
    set_clock(api, "2026-08-11T09:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "empty@example.com", "Ellie Empty")
    return create_booking(
        api, passenger["id"], profile["id"], "EMP001", 100000, "CREDIT_CARD"
    )


class TestZeroSegmentExposureGuard:
    def test_an_itinerary_with_no_legs_prorates_to_zero_without_dividing(self, api):
        """The empty-set guard answers 200 with a request-based figure of 0.

        PRD §3.6: "In request-based mode the variant is
        `REQUEST_BASED_UNUSED_PRORATION`, and it prorates evenly: when the booking's
        `segment_count` is 0 the gross entitlement is 0 and no division is attempted,
        and otherwise the per-leg share is the booking's `total_fare_cents` divided by
        its `segment_count` and rounded half up, and the gross entitlement is that share
        multiplied by the booking's `unused_segment_count`."

        Design: Difficulty/boundary_precision_check/refund_exposure_zero_segment_empty_set_guard
        """
        booking = _booking_without_legs(api)

        exposure = validate_success(api.get_refund_exposure(booking["id"], OFFICER_HEADERS))

        assert_exposure(
            exposure,
            segment_count=0,
            unused_segment_count=0,
            travel_commenced=False,
            request_based_proration_cents=0,
        )

    def test_the_proactive_variant_still_values_the_whole_untravelled_fare(self, api):
        """With travel not commenced the proactive figure is the whole ticketed fare.

        PRD §3.6: "`variant_delta_cents`, the proactive figure minus the request-based
        figure; `obligated_total_cents`, mirroring the booking's
        `total_refund_obligated_cents`; `remaining_headroom_cents`, computed exactly as
        step two above; `collected_total_cents`; `segment_count`;
        `unused_segment_count`; and `travel_commenced`."

        Design: Difficulty/boundary_precision_check/refund_exposure_zero_segment_empty_set_guard
        """
        booking = _booking_without_legs(api)

        assert_exposure(
            read_exposure(api, booking["id"]),
            proactive_full_itinerary_cents=100000,
            variant_delta_cents=100000,
            collected_total_cents=100000,
            obligated_total_cents=0,
            remaining_headroom_cents=100000,
        )
        assert_booking_ledger(
            read_booking(api, booking["id"]), disruption_posture="NORMAL"
        )
