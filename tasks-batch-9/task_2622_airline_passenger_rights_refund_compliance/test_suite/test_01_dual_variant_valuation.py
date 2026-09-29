"""The two twin-valuation rules: fare variants and the denied-boarding pair."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_HEADERS,
    OPS_HEADERS,
    assert_booking_ledger,
    assert_cents,
    assert_exposure,
    create_booking,
    create_passenger,
    create_policy_profile,
    factories as f,
    read_booking,
    read_denied_boarding,
    read_exposure,
    record_operation,
    set_clock,
)


def _partly_flown_itinerary(api):
    """100000-cent fare over three unevenly priced legs, first leg flown."""
    set_clock(api, "2026-08-10T18:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "pat.dual@example.com", "Pat Dual")
    booking = create_booking(
        api, passenger["id"], profile["id"], "ABC123", 100000, "CREDIT_CARD"
    )
    fares = [20000, 40000, 40000]
    legs = [
        ("ZQ101", "LAX", "DEN", "2026-08-10T14:00:00Z", "2026-08-10T17:00:00Z"),
        ("ZQ202", "DEN", "ORD", "2026-08-10T18:30:00Z", "2026-08-10T21:00:00Z"),
        ("ZQ303", "ORD", "BOS", "2026-08-11T13:00:00Z", "2026-08-11T16:00:00Z"),
    ]
    segments = []
    for index, (number, origin, destination, departure, arrival) in enumerate(legs, 1):
        response = api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=index,
                flight_number=number,
                origin_iata=origin,
                destination_iata=destination,
                scheduled_departure_utc=departure,
                scheduled_arrival_utc=arrival,
                segment_fare_cents=fares[index - 1],
            ),
            OPS_HEADERS,
        )
        segments.append(validate_success(response, 201))
    record_operation(api, segments[0]["id"], "DEPARTED", "2026-08-10T14:10:00Z")
    return booking, segments


class TestFareVariantDivergence:
    def test_proactive_and_request_based_fare_variants_diverge_by_13334_cents(self, api):
        """A partly flown itinerary values at 80000 proactively and 66666 request-based.

        PRD §3.6: "In proactive mode the variant is `PROACTIVE_FULL_ITINERARY`: when
        the booking's `travel_commenced` is false, `gross_entitlement_cents` is the
        booking's whole `total_fare_cents`; when travel has commenced, it is the sum of
        `segment_fare_cents` over the booking's legs whose `status` is `SCHEDULED`,
        `DELAYED`, `CANCELLED` or `DISRUPTED_UNUSED`, added in ascending
        `sequence_index` order with no intermediate rounding since each per-leg fare is
        already whole cents."

        PRD §3.6: "In request-based mode the variant is
        `REQUEST_BASED_UNUSED_PRORATION`, and it prorates evenly: when the booking's
        `segment_count` is 0 the gross entitlement is 0 and no division is attempted,
        and otherwise the per-leg share is the booking's `total_fare_cents` divided by
        its `segment_count` and rounded half up, and the gross entitlement is that
        share multiplied by the booking's `unused_segment_count`."

        Design: Difficulty/dual_variant_calc/fare_variant_divergence_on_partly_flown_itinerary
        """
        booking, _ = _partly_flown_itinerary(api)

        exposure = read_exposure(api, booking["id"])

        assert_exposure(
            exposure,
            proactive_full_itinerary_cents=80000,
            request_based_proration_cents=66666,
            variant_delta_cents=13334,
            segment_count=3,
            unused_segment_count=2,
            travel_commenced=True,
        )

    def test_refund_exposure_is_a_pure_read_that_persists_nothing(self, api):
        """The exposure read reports headroom and collected money without writing.

        PRD §3.6: "Nothing is written and no `version` moves."

        Design: Difficulty/dual_variant_calc/fare_variant_divergence_on_partly_flown_itinerary
        """
        booking, _ = _partly_flown_itinerary(api)
        before = read_booking(api, booking["id"])

        exposure = read_exposure(api, booking["id"])
        after = read_booking(api, booking["id"])

        assert_exposure(
            exposure,
            collected_total_cents=100000,
            remaining_headroom_cents=100000,
            obligated_total_cents=0,
        )
        assert_booking_ledger(after, total_refund_obligated_cents=0)
        assert after["version"] == before["version"], (
            "reading the exposure view must not advance the booking's version"
        )


def _denied_boarding_pair(api):
    """Identical fare and identical 90-minute substitute delay, opposite categories."""
    set_clock(api, "2026-08-11T09:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "dbc.pair@example.com", "Dana Bordeaux")
    booking = create_booking(
        api, passenger["id"], profile["id"], "DBC001", 90000, "CREDIT_CARD"
    )
    seg1 = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ101",
                origin_iata="LAX",
                destination_iata="DEN",
                scheduled_departure_utc="2026-08-10T14:00:00Z",
                scheduled_arrival_utc="2026-08-10T17:00:00Z",
                segment_fare_cents=45000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    seg2 = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=2,
                flight_number="ZQ202",
                origin_iata="DEN",
                destination_iata="ORD",
                scheduled_departure_utc="2026-08-10T18:30:00Z",
                scheduled_arrival_utc="2026-08-10T21:00:00Z",
                segment_fare_cents=45000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    involuntary = validate_success(
        api.create_denied_boarding_record(
            f.denied_boarding_payload(
                booking["id"],
                seg1["id"],
                "INVOLUNTARY",
                45000,
                "2026-08-10T18:30:00Z",
                oversale_confirmed=True,
                written_disclosure_provided=True,
            ),
            OFFICER_HEADERS,
        ),
        201,
    )
    voluntary = validate_success(
        api.create_denied_boarding_record(
            f.denied_boarding_payload(
                booking["id"],
                seg2["id"],
                "VOLUNTARY",
                45000,
                "2026-08-10T22:30:00Z",
                oversale_confirmed=True,
                written_disclosure_provided=True,
                voluntary_agreed_amount_cents=50000,
            ),
            OFFICER_HEADERS,
        ),
        201,
    )
    for record in (involuntary, voluntary):
        validate_success(
            api.finalize_denied_boarding_record(
                record["id"], f.finalize_payload("2026-08-11T09:00:00Z"), OFFICER_HEADERS
            )
        )
    return booking, involuntary, voluntary


class TestDeniedBoardingStatutoryVersusNegotiated:
    def test_identical_fare_and_delay_pay_77500_involuntarily_and_50000_voluntarily(
        self, api
    ):
        """The same 45000 fare and same 90-minute delay diverge by 27500 cents.

        PRD §3.4: "On an involuntary record `compensation_cents` is set to
        `statutory_compensation_cents`."

        PRD §3.4: "when it clears the floor, `compensation_cents` is set to the agreed
        amount, which may sit anywhere at or above the floor."

        Design: Difficulty/dual_variant_calc/denied_boarding_involuntary_statutory_vs_voluntary_negotiated
        """
        _, involuntary_id, voluntary_id = _denied_boarding_pair(api)

        involuntary = read_denied_boarding(api, involuntary_id["id"])
        voluntary = read_denied_boarding(api, voluntary_id["id"])

        assert involuntary["substitute_delay_minutes"] == 90
        assert voluntary["substitute_delay_minutes"] == 90
        assert_cents(
            involuntary["statutory_compensation_cents"], 77500, "statutory_compensation_cents"
        )
        assert_cents(
            voluntary["statutory_compensation_cents"], 77500, "statutory_compensation_cents"
        )
        assert_cents(involuntary["compensation_cents"], 77500, "compensation_cents")
        assert_cents(voluntary["compensation_cents"], 50000, "compensation_cents")
        assert involuntary["effective_category"] == "INVOLUNTARY"
        assert voluntary["effective_category"] == "VOLUNTARY"
        assert involuntary["status"] == "FINALIZED"
        assert voluntary["status"] == "FINALIZED"
        assert (
            involuntary["compensation_cents"] - voluntary["compensation_cents"] == 27500
        ), "the two records must diverge by exactly 27500 cents"

    def test_denied_boarding_obligations_may_exceed_the_money_collected(self, api):
        """127500 cents of compensation stands on a booking that collected 90000.

        PRD §3.4: "Statutory denied-boarding compensation is **exempt from the
        booking's refund headroom entirely** — it is compensation for a service failure
        rather than a refund of money collected, so it is neither clamped by the
        headroom nor counted against it when later obligations compute theirs."

        Design: Difficulty/dual_variant_calc/denied_boarding_involuntary_statutory_vs_voluntary_negotiated
        """
        booking, _, _ = _denied_boarding_pair(api)

        rows, meta = validate_paginated(
            api.list_refund_obligations(
                ADMIN_HEADERS, booking_id=booking["id"], basis="DENIED_BOARDING"
            )
        )
        stored = read_booking(api, booking["id"])

        assert meta["total_count"] == 2, "each finalized record mints one obligation"
        assert sorted(row["amount_cents"] for row in rows) == [50000, 77500]
        assert_booking_ledger(
            stored, collected_total_cents=90000, total_refund_obligated_cents=127500
        )
