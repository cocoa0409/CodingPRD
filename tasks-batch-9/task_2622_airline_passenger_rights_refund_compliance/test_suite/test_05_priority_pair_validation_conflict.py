"""Requests that break two rules at once, and which rule the contract reports."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ERR_OBLIGATION_STATE_INVALID,
    ERR_REFUND_EXCEEDS_HEADROOM,
    ERR_SEGMENT_BOOKING_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TARMAC_INTERVAL_OVERLAP,
    ERR_TARMAC_WINDOW_INVALID,
    OFFICER_2_HEADERS,
    OFFICER_3_HEADERS,
    OFFICER_HEADERS,
    OPS_HEADERS,
    acknowledge,
    answer,
    assert_booking_ledger,
    assert_exposure,
    assert_null,
    assert_obligation_axes,
    assert_segment_state,
    booking_version,
    cancel_segment,
    complete,
    create_booking,
    create_passenger,
    create_policy_profile,
    elect,
    factories as f,
    file_complaint,
    initiate,
    obligations_with_meta,
    read_booking,
    read_exposure,
    read_obligation,
    read_segment,
    read_tarmac_event,
    set_clock,
    sole_obligation,
    void,
)

# ─── Resource state versus segregation of duties ──────


def _officer_minted_request_based_obligation(
    api, profile_id, passenger_id, record_locator, fare, flight_number, origin, destination
):
    """Cancel the leg, discard the cascade row, and re-mint it by hand as officer_1."""
    booking = create_booking(
        api, passenger_id, profile_id, record_locator, fare, "CREDIT_CARD"
    )
    segment = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number=flight_number,
                origin_iata=origin,
                destination_iata=destination,
                scheduled_departure_utc="2026-08-12T20:00:00Z",
                scheduled_arrival_utc="2026-08-12T23:00:00Z",
                segment_fare_cents=fare,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    cancel_segment(api, segment["id"], "2026-08-10T18:00:00Z")
    void(api, sole_obligation(api, booking["id"])["id"], "CREATED_IN_ERROR")
    minted = validate_success(
        api.create_refund_obligation(
            f.obligation_payload(
                booking["id"],
                booking_version(api, booking["id"]),
                "FARE",
                "REQUEST_BASED",
                flight_segment_id=segment["id"],
            ),
            OFFICER_HEADERS,
        ),
        201,
    )
    elect(api, minted["id"], "CASH", OFFICER_HEADERS)
    return booking, minted


def _settled_and_unsettled_pair(api):
    """Two obligations minted by the same officer; one settled, one still open."""
    set_clock(api, "2026-08-10T18:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "duties@example.com", "Dee Duties")
    settled_booking, settled = _officer_minted_request_based_obligation(
        api, profile["id"], passenger["id"], "SOD001", 60000, "ZQ303", "LAX", "DEN"
    )
    initiate(api, settled["id"], OFFICER_2_HEADERS)
    complete(api, settled["id"], OFFICER_3_HEADERS, outcome="SUCCEEDED")
    open_booking, still_open = _officer_minted_request_based_obligation(
        api, profile["id"], passenger["id"], "SOD002", 30000, "ZQ404", "SFO", "SEA"
    )
    return settled_booking, settled, open_booking, still_open


class TestSettledStateBeatsSegregationOfDuties:
    def test_the_creating_officer_hits_the_state_check_not_the_duties_check(self, api):
        """On a settled row the wrong-state refusal outranks the same officer's conflict.

        PRD §2.5: "**State of the addressed resource** — the row named in the path must
        be in a state from which the requested transition exists."

        PRD §2.5: "**Regulatory safety gates**, in this order: segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), the officer credit-consent requirement
        (`ERR_CREDIT_CONSENT_REQUIRED`), the disability resolution-code requirement
        (`ERR_ACCESSIBILITY_RESOLUTION_REQUIRED`), the voluntary disclosure floor
        (`ERR_VOLUNTARY_BELOW_DISCLOSURE_FLOOR`), and the corrective-action requirement
        on a violating tarmac report (`ERR_CORRECTIVE_ACTION_REQUIRED`) — the last four
        all HTTP 422."

        Design: Difficulty/priority_pair_validation_conflict/settled_obligation_state_beats_segregation_of_duties
        """
        settled_booking, settled, _, _ = _settled_and_unsettled_pair(api)

        refused = api.initiate_settlement(
            settled["id"], f.initiate_payload("PROC-RETRY"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_OBLIGATION_STATE_INVALID, 409)
        assert_obligation_axes(
            read_obligation(api, settled["id"]),
            settlement_status="SETTLED",
            settlement_attempt_count=1,
        )
        assert_booking_ledger(
            read_booking(api, settled_booking["id"]), disruption_posture="CLOSED_OUT"
        )

    def test_the_same_officer_on_an_unsettled_row_hits_the_duties_check(self, api):
        """With the state gate satisfied, the officer who minted the row cannot pay it.

        PRD §3.7: "And `X-User-ID` must differ from the obligation's
        `created_by_user_id`, or the answer is `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/settled_obligation_state_beats_segregation_of_duties
        """
        _, _, open_booking, still_open = _settled_and_unsettled_pair(api)

        refused = api.initiate_settlement(
            still_open["id"], f.initiate_payload("PROC-0002"), OFFICER_HEADERS
        )

        validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)
        assert_obligation_axes(
            read_obligation(api, still_open["id"]),
            settlement_status="UNSETTLED",
            settlement_attempt_count=0,
        )
        assert_booking_ledger(
            read_booking(api, open_booking["id"]), disruption_posture="REFUND_OBLIGATED"
        )


# ─── Temporal window versus interval overlap ──────────


def _open_tarmac_occupation(api):
    """One leg with a single occupation left open, so it blocks everything after it."""
    set_clock(api, "2026-08-10T22:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "window@example.com", "Win Doe")
    booking = create_booking(
        api, passenger["id"], profile["id"], "WIN001", 30000, "CREDIT_CARD"
    )
    segment = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ202",
                origin_iata="DEN",
                destination_iata="ORD",
                scheduled_departure_utc="2026-08-10T18:30:00Z",
                scheduled_arrival_utc="2026-08-10T21:00:00Z",
                segment_fare_cents=30000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    event = validate_success(
        api.create_tarmac_delay_event(
            f.tarmac_event_payload(segment["id"], "2026-08-10T18:40:00Z", "DEPARTURE"),
            OPS_HEADERS,
        ),
        201,
    )
    return profile, segment, event


class TestTarmacWindowBeatsIntervalOverlap:
    def test_a_start_before_scheduled_departure_reports_the_window_not_the_overlap(
        self, api
    ):
        """18:00 is both pre-departure and inside the open occupation; the window wins.

        PRD §3.5: "Whichever phase is declared, the start instant must be at or after
        the leg's `scheduled_departure_utc`; an earlier instant is never a tarmac
        occupation and is refused with `ERR_TARMAC_WINDOW_INVALID`."

        PRD §2.5: "**Temporal gates**, in this order: `ERR_TARMAC_WINDOW_INVALID`,
        `ERR_EXEMPTION_AFTER_DEADLINE`, `ERR_DELIVERY_BEFORE_CHECKIN`,
        `ERR_ANSWER_BEFORE_RECEIPT`, `ERR_PERIOD_BOUNDS_INVALID`,
        `ERR_SUBSTITUTE_BEFORE_SCHEDULED` and `ERR_REVISED_ARRIVAL_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/tarmac_window_temporal_beats_interval_overlap_constraint
        """
        _, segment, event = _open_tarmac_occupation(api)

        refused = api.create_tarmac_delay_event(
            f.tarmac_event_payload(segment["id"], "2026-08-10T18:00:00Z", "DEPARTURE"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_TARMAC_WINDOW_INVALID, 422)
        _, meta = validate_paginated(
            api.list_segment_tarmac_events(segment["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1, "a refused create must not persist a row"

    def test_a_legal_start_inside_the_open_occupation_reports_the_overlap(self, api):
        """21:00 clears the window rule and then collides with the unbounded occupation.

        PRD §3.5: "A closed event occupies the interval from its `tarmac_start_utc`
        inclusive to its `interval_end_utc` exclusive; an event still open occupies
        everything from its `tarmac_start_utc` onward without end, and therefore blocks
        every later event on the same leg until it is closed."

        PRD §3.5: "A new event whose interval intersects any existing occupation is
        refused with `ERR_TARMAC_INTERVAL_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/tarmac_window_temporal_beats_interval_overlap_constraint
        """
        _, segment, event = _open_tarmac_occupation(api)

        refused = api.create_tarmac_delay_event(
            f.tarmac_event_payload(segment["id"], "2026-08-10T21:00:00Z", "ARRIVAL"),
            OPS_HEADERS,
        )

        validate_error(refused, ERR_TARMAC_INTERVAL_OVERLAP, 409)
        stored = read_tarmac_event(api, event["id"], segment["id"])
        assert stored["status"] == "DELAY_ACTIVE"
        assert_null(stored["interval_end_utc"], "interval_end_utc")
        assert stored["tarmac_minutes"] == 0
        assert_segment_state(
            read_segment(api, segment["id"]), cumulative_tarmac_minutes=0
        )


# ─── Referential consistency versus fiscal checks ─────


def _two_bookings_with_a_thin_ledger(api):
    """Booking A collected 10000 and already owes 9000, so only 1000 is left."""
    set_clock(api, "2026-08-11T12:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "thin@example.com", "Thea Ledger")
    booking_a = create_booking(
        api, passenger["id"], profile["id"], "AAA111", 10000, "CREDIT_CARD"
    )
    segment_a = validate_success(
        api.create_flight_segment(
            booking_a["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ101",
                origin_iata="LAX",
                destination_iata="DEN",
                scheduled_departure_utc="2026-08-12T14:00:00Z",
                scheduled_arrival_utc="2026-08-12T17:00:00Z",
                segment_fare_cents=10000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    booking_b = create_booking(
        api, passenger["id"], profile["id"], "BBB222", 50000, "CREDIT_CARD"
    )
    segment_b = validate_success(
        api.create_flight_segment(
            booking_b["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ505",
                origin_iata="JFK",
                destination_iata="MIA",
                scheduled_departure_utc="2026-08-12T18:00:00Z",
                scheduled_arrival_utc="2026-08-12T21:00:00Z",
                segment_fare_cents=50000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    complaint = file_complaint(
        api,
        booking_a["id"],
        category="REFUND",
        channel="WEB",
        received_at_utc="2026-08-11T08:00:00Z",
    )
    acknowledge(api, complaint["id"], "2026-08-11T09:00:00Z")
    answer(
        api,
        complaint["id"],
        "2026-08-11T10:00:00Z",
        "REFUND_GRANTED",
        granted_amount_cents=9000,
    )
    return booking_a, segment_a, booking_b, segment_b


class TestSegmentBookingMismatchBeatsHeadroom:
    def test_naming_another_bookings_leg_reports_the_mismatch_not_the_shortfall(self, api):
        """The referential check fires even though the amount is also unaffordable.

        PRD §3.6: "The narrower check fires first: when a `flight_segment_id` is
        supplied and the leg it names belongs to a different booking than the
        `booking_id` in the body, the answer is `ERR_SEGMENT_BOOKING_MISMATCH`."

        PRD §2.5: "**Fiscal checks, evaluated last** — `ERR_NO_REFUND_HEADROOM` and
        `ERR_REFUND_EXCEEDS_HEADROOM`, both HTTP 422. Money is the last thing checked,
        so a request that is both malformed and unaffordable reports the malformation."

        Design: Difficulty/priority_pair_validation_conflict/segment_booking_mismatch_referential_beats_headroom_fiscal
        """
        booking_a, _, _, segment_b = _two_bookings_with_a_thin_ledger(api)
        version_before = booking_version(api, booking_a["id"])

        refused = api.create_refund_obligation(
            f.obligation_payload(
                booking_a["id"],
                version_before,
                "FARE",
                "REQUEST_BASED",
                flight_segment_id=segment_b["id"],
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_SEGMENT_BOOKING_MISMATCH, 422)
        stored = read_booking(api, booking_a["id"])
        assert stored["version"] == version_before, "a refused create writes nothing"
        _, meta = obligations_with_meta(api, booking_a["id"])
        assert meta["total_count"] == 1, "only the goodwill grant exists"

    def test_the_same_request_on_the_right_leg_reports_the_shortfall(self, api):
        """With the reference corrected, 10000 requested against 1000 available fails.

        PRD §3.6: "A request-based obligation is never clamped: if its gross entitlement
        exceeds the headroom, the request is refused with `ERR_REFUND_EXCEEDS_HEADROOM`,
        because a passenger-initiated claim that the ledger cannot support is an error to
        be corrected rather than a number to be silently reduced."

        Design: Difficulty/priority_pair_validation_conflict/segment_booking_mismatch_referential_beats_headroom_fiscal
        """
        booking_a, segment_a, _, _ = _two_bookings_with_a_thin_ledger(api)
        version_before = booking_version(api, booking_a["id"])

        refused = api.create_refund_obligation(
            f.obligation_payload(
                booking_a["id"],
                version_before,
                "FARE",
                "REQUEST_BASED",
                flight_segment_id=segment_a["id"],
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_REFUND_EXCEEDS_HEADROOM, 422)
        assert_booking_ledger(
            read_booking(api, booking_a["id"]),
            collected_total_cents=10000,
            total_refund_obligated_cents=9000,
        )
        assert_exposure(
            read_exposure(api, booking_a["id"]),
            remaining_headroom_cents=1000,
            request_based_proration_cents=10000,
        )
