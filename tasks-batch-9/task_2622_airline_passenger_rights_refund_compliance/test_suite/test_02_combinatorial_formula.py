"""Formulas whose operand order is pinned: the ladder, the proration, the headroom."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_HEADERS,
    OPS_HEADERS,
    acknowledge,
    add_ancillary,
    answer,
    assert_booking_ledger,
    assert_cents,
    assert_obligation_amounts,
    assert_obligation_deadlines,
    booking_version,
    cancel_segment,
    create_booking,
    create_passenger,
    create_policy_profile,
    factories as f,
    file_complaint,
    obligations_with_meta,
    read_ancillary,
    read_booking,
    read_denied_boarding,
    read_obligation,
    record_operation,
    set_clock,
    sole_obligation,
    void,
)

# ─── Shared worlds ────────────────────────────────────


def _two_leg_denied_boarding_world(api):
    set_clock(api, "2026-08-11T09:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "ladder@example.com", "Lee Ladder")
    booking = create_booking(
        api, passenger["id"], profile["id"], "LAD001", 90000, "CREDIT_CARD"
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
    return booking, seg1, seg2


def _finalized_involuntary(api, booking_id, segment_id, substitute_arrival_utc):
    record = validate_success(
        api.create_denied_boarding_record(
            f.denied_boarding_payload(
                booking_id,
                segment_id,
                "INVOLUNTARY",
                45000,
                substitute_arrival_utc,
                oversale_confirmed=True,
                written_disclosure_provided=True,
            ),
            OFFICER_HEADERS,
        ),
        201,
    )
    validate_success(
        api.finalize_denied_boarding_record(
            record["id"], f.finalize_payload("2026-08-11T09:00:00Z"), OFFICER_HEADERS
        )
    )
    return read_denied_boarding(api, record["id"])


def _ladder_pair(api):
    """Two 45000-cent denials at 120 and 121 minutes of substitute delay."""
    booking, seg1, seg2 = _two_leg_denied_boarding_world(api)
    at_ceiling = _finalized_involuntary(
        api, booking["id"], seg1["id"], "2026-08-10T19:00:00Z"
    )
    past_ceiling = _finalized_involuntary(
        api, booking["id"], seg2["id"], "2026-08-10T23:01:00Z"
    )
    return booking, at_ceiling, past_ceiling


class TestDeniedBoardingLadderNestedMinAndCap:
    def test_both_rungs_round_the_fare_multiple_before_hitting_their_caps(self, api):
        """2x45000 caps at 77500 and 4x45000 caps at 155000 on the same fare.

        PRD §3.4: "The second rung runs from 61 minutes up to and including a
        scope-dependent ceiling of 120 minutes (two hours) on a domestic leg or 240
        minutes (four hours) on a leg flagged international; here the statutory figure
        is twice the `one_way_fare_cents`, rounded half up, but never more than 77,500
        cents (775 dollars)."

        PRD §3.4: "In both paid rungs the rounding is applied to the fare multiple
        **before** the cap comparison, not after it."

        Design: Difficulty/combinatorial_formula/denied_boarding_tier_ladder_nested_min_and_cap
        """
        _, at_ceiling, past_ceiling = _ladder_pair(api)

        assert at_ceiling["substitute_delay_minutes"] == 120
        assert past_ceiling["substitute_delay_minutes"] == 121
        assert_cents(
            at_ceiling["statutory_compensation_cents"], 77500, "statutory_compensation_cents"
        )
        assert_cents(
            past_ceiling["statutory_compensation_cents"],
            155000,
            "statutory_compensation_cents",
        )
        assert_cents(at_ceiling["compensation_cents"], 77500, "compensation_cents")
        assert_cents(past_ceiling["compensation_cents"], 155000, "compensation_cents")

    def test_one_minute_past_the_domestic_ceiling_moves_to_the_four_times_rung(self, api):
        """The step from 120 to 121 minutes doubles the carrier's exposure.

        PRD §3.4: "Beyond that ceiling — one minute past two hours domestically, one
        minute past four hours internationally — the statutory figure is four times the
        `one_way_fare_cents`, rounded half up, but never more than 155,000 cents (1,550
        dollars)."

        Design: Difficulty/combinatorial_formula/denied_boarding_tier_ladder_nested_min_and_cap
        """
        booking, at_ceiling, past_ceiling = _ladder_pair(api)

        assert at_ceiling["status"] == "FINALIZED"
        assert past_ceiling["status"] == "FINALIZED"
        assert past_ceiling["compensation_cents"] == 2 * at_ceiling["compensation_cents"]
        rows, meta = validate_paginated(
            api.list_refund_obligations(
                ADMIN_HEADERS, booking_id=booking["id"], basis="DENIED_BOARDING"
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["amount_cents"] for row in rows) == [77500, 155000]
        assert_booking_ledger(
            read_booking(api, booking["id"]), total_refund_obligated_cents=232500
        )


# ─── Request-based proration ──────────────────────────


def _prorated_request_obligation(api):
    """100000 over three legs, first flown, second cancelled, then re-minted by hand."""
    set_clock(api, "2026-08-10T18:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "prorate@example.com", "Robin Prorata")
    booking = create_booking(
        api, passenger["id"], profile["id"], "PRO001", 100000, "CREDIT_CARD"
    )
    legs = [
        (1, "ZQ101", "LAX", "DEN", "2026-08-10T14:00:00Z", "2026-08-10T17:00:00Z", 20000),
        (2, "ZQ202", "DEN", "ORD", "2026-08-10T18:30:00Z", "2026-08-10T21:00:00Z", 40000),
        (3, "ZQ303", "ORD", "BOS", "2026-08-11T13:00:00Z", "2026-08-11T16:00:00Z", 40000),
    ]
    segments = []
    for index, number, origin, destination, departure, arrival, fare in legs:
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
                        segment_fare_cents=fare,
                    ),
                    OPS_HEADERS,
                ),
                201,
            )
        )
    record_operation(api, segments[0]["id"], "DEPARTED", "2026-08-10T14:10:00Z")
    cancel_segment(api, segments[1]["id"], "2026-08-10T18:00:00Z")
    cascade = sole_obligation(api, booking["id"])
    void(api, cascade["id"], "CREATED_IN_ERROR")
    minted = validate_success(
        api.create_refund_obligation(
            f.obligation_payload(
                booking["id"],
                booking_version(api, booking["id"]),
                "FARE",
                "REQUEST_BASED",
                flight_segment_id=segments[1]["id"],
            ),
            OFFICER_HEADERS,
        ),
        201,
    )
    return booking, minted


class TestRequestBasedProrationRoundingOrder:
    def test_per_leg_share_is_rounded_before_the_unused_leg_multiply(self, api):
        """100000 over three legs with two unused yields 66666, never 66667.

        PRD §3.6: "In request-based mode the variant is
        `REQUEST_BASED_UNUSED_PRORATION`, and it prorates evenly: when the booking's
        `segment_count` is 0 the gross entitlement is 0 and no division is attempted,
        and otherwise the per-leg share is the booking's `total_fare_cents` divided by
        its `segment_count` and rounded half up, and the gross entitlement is that
        share multiplied by the booking's `unused_segment_count`."

        PRD §3.6: "The rounding order is pinned and must not be rearranged: round the
        per-leg share **first**, then multiply by the unused-leg count."

        Design: Difficulty/combinatorial_formula/request_based_proration_rounds_per_segment_before_multiplying
        """
        booking, minted = _prorated_request_obligation(api)

        obligation = read_obligation(api, minted["id"])

        assert obligation["variant_applied"] == "REQUEST_BASED_UNUSED_PRORATION"
        assert_obligation_amounts(
            obligation,
            gross_entitlement_cents=66666,
            headroom_at_creation_cents=100000,
            amount_cents=66666,
            payable_total_cents=66666,
        )
        assert obligation["gross_entitlement_cents"] != 66667, (
            "multiplying before rounding would yield 66667"
        )
        assert_booking_ledger(
            read_booking(api, booking["id"]),
            total_refund_obligated_cents=66666,
            unused_segment_count=2,
        )

    def test_credit_card_settlement_and_election_deadlines_run_from_the_declaration(
        self, api
    ):
        """A credit-card booking gets seven days to settle and five to elect.

        PRD §3.6: "From the start instant, `deadline_utc` is the settlement deadline:
        the number of days configured for credit-card payments when the booking's
        `payment_method` is `CREDIT_CARD`, and the number configured for every other
        form of payment otherwise — seven days against twenty days under the regulatory
        defaults, which is why the form of payment collected at booking time still
        matters months later."

        PRD §3.6: "And `election_deadline_utc` is five days after the start instant,
        this election window being a statutory constant the carrier cannot tune."

        Design: Difficulty/combinatorial_formula/request_based_proration_rounds_per_segment_before_multiplying
        """
        _, minted = _prorated_request_obligation(api)

        obligation = read_obligation(api, minted["id"])

        assert_obligation_deadlines(
            obligation,
            obligation_start_utc="2026-08-10T18:00:00Z",
            deadline_utc="2026-08-17T18:00:00Z",
            election_deadline_utc="2026-08-15T18:00:00Z",
            deadline_breached=False,
        )


# ─── Headroom evaluation order ────────────────────────


def _exhausted_headroom_cascade(api):
    """A 15000-cent goodwill grant leaves only 5400 of a 20400-cent ledger."""
    set_clock(api, "2026-08-12T00:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "headroom@example.com", "Hal Headroom")
    booking = create_booking(
        api, passenger["id"], profile["id"], "HDR001", 14000, "CREDIT_CARD"
    )
    segment = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ101",
                origin_iata="LAX",
                destination_iata="DEN",
                scheduled_departure_utc="2026-08-12T14:00:00Z",
                scheduled_arrival_utc="2026-08-12T17:00:00Z",
                segment_fare_cents=14000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    seat = add_ancillary(api, booking["id"], segment["id"], "SEAT_SELECTION", 4500)
    entertainment = add_ancillary(api, booking["id"], segment["id"], "ENTERTAINMENT", 1900)
    complaint = file_complaint(
        api,
        booking["id"],
        category="REFUND",
        channel="WEB",
        received_at_utc="2026-08-11T10:00:00Z",
    )
    acknowledge(api, complaint["id"], "2026-08-11T12:00:00Z")
    answer(
        api,
        complaint["id"],
        "2026-08-11T13:00:00Z",
        "REFUND_GRANTED",
        granted_amount_cents=15000,
    )
    cancel_segment(api, segment["id"], "2026-08-11T14:00:00Z")
    return booking, seat, entertainment


class TestHeadroomEvaluationOrder:
    def test_fare_obligation_is_clamped_to_the_headroom_the_grant_left_behind(self, api):
        """A 14000-cent fare entitlement is clamped down to the 5400 still available.

        PRD §3.6: "Step two computes the booking's headroom over **strictly
        pre-existing** obligations only — the row being created is not yet persisted
        and contributes nothing to its own headroom."

        PRD §3.6: "A proactive obligation is clamped down: its `amount_cents` is the
        smaller of its gross entitlement and the headroom — but a proactive create
        against a booking whose headroom is 0 or negative is refused outright with
        `ERR_NO_REFUND_HEADROOM`."

        Design: Difficulty/combinatorial_formula/headroom_evaluation_order_clamps_cascade_in_pinned_sequence
        """
        booking, _, _ = _exhausted_headroom_cascade(api)

        fare = sole_obligation(api, booking["id"], basis="FARE")

        assert_obligation_amounts(
            fare,
            gross_entitlement_cents=14000,
            headroom_at_creation_cents=5400,
            amount_cents=5400,
        )

    def test_ancillary_links_are_suppressed_once_the_ledger_is_exhausted(self, api):
        """Both extras flip to NOT_PROVIDED yet neither earns an obligation row.

        PRD §3.2: "An ancillary whose clamp yields zero is skipped instead: no
        obligation row is written, that ancillary's `refund_obligation_created` stays
        false, and the booking's `suppressed_obligation_count` increases by 1."

        PRD §3.2: "**Link two-b,** also caused by link one: every ancillary purchase
        attached to the cancelled leg whose `delivery_status` is `PENDING_DELIVERY`
        becomes `NOT_PROVIDED` with `non_provision_reason` set to `SERVICE_CANCELLED`,
        processed in ascending `created_at` order."

        Design: Difficulty/combinatorial_formula/headroom_evaluation_order_clamps_cascade_in_pinned_sequence
        """
        booking, seat, entertainment = _exhausted_headroom_cascade(api)

        _, meta = obligations_with_meta(api, booking["id"], basis="ANCILLARY")
        assert meta["total_count"] == 0, "an exhausted ledger writes no ancillary rows"

        for purchase_id in (seat["id"], entertainment["id"]):
            purchase = read_ancillary(api, purchase_id)
            assert purchase["delivery_status"] == "NOT_PROVIDED"
            assert purchase["non_provision_reason"] == "SERVICE_CANCELLED"
            assert purchase["refund_obligation_created"] is False

        assert_booking_ledger(
            read_booking(api, booking["id"]),
            collected_total_cents=20400,
            total_refund_obligated_cents=20400,
            suppressed_obligation_count=2,
            disruption_posture="REFUND_OBLIGATED",
        )
