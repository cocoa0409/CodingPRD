"""Undoing money moves and proving both conserved ledgers land back on the cent."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    OFFICER_2_HEADERS,
    OFFICER_3_HEADERS,
    OPS_HEADERS,
    add_ancillary,
    assert_booking_ledger,
    assert_instant,
    assert_null,
    assert_obligated_ledger,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_travel_credit_ledger,
    build_world,
    cancel_segment,
    complete,
    create_booking,
    create_passenger,
    create_policy_profile,
    elect,
    factories as f,
    initiate,
    list_obligations,
    read_ancillary,
    read_booking,
    read_obligation,
    read_passenger,
    set_clock,
    sole_obligation,
    void,
)

# ─── Voiding an ancillary obligation ──────────────────


def _cascade_with_two_ancillary_obligations(api):
    """A cancelled middle leg leaving one fare row and two face-value extras."""
    set_clock(api, "2026-08-10T18:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "undo@example.com", "Una Undo")
    booking = create_booking(
        api, passenger["id"], profile["id"], "UND001", 100000, "CREDIT_CARD"
    )
    legs = [
        (1, "ZQ101", "LAX", "DEN", "2026-08-12T14:00:00Z", "2026-08-12T17:00:00Z", 20000),
        (2, "ZQ202", "DEN", "ORD", "2026-08-12T18:30:00Z", "2026-08-12T21:00:00Z", 40000),
        (3, "ZQ303", "ORD", "BOS", "2026-08-13T13:00:00Z", "2026-08-13T16:00:00Z", 40000),
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
    seat = add_ancillary(api, booking["id"], segments[1]["id"], "SEAT_SELECTION", 4500)
    entertainment = add_ancillary(
        api, booking["id"], segments[1]["id"], "ENTERTAINMENT", 1900
    )
    cancel_segment(api, segments[1]["id"], "2026-08-10T18:00:00Z")
    seat_obligation = sole_obligation(
        api, booking["id"], basis="ANCILLARY", ancillary_purchase_id=seat["id"]
    )
    return booking, seat, entertainment, seat_obligation


class TestAncillaryVoidRestoresTheObligatedLedger:
    def test_voiding_the_seat_obligation_returns_the_ledger_to_its_pre_create_value(
        self, api
    ):
        """106400 obligated cents fall to exactly 101900 with no residual drift.

        PRD §2.11: "The practical consequence is compensating symmetry: if an obligation
        of some amount is minted and then voided, the booking's
        `total_refund_obligated_cents` after the void equals its value before the create,
        exactly, with no residual drift, and the booking's `disruption_posture` returns to
        the value it held before the create."

        PRD §2.11: "Voiding never deletes a row — the row persists with a voided
        settlement axis and a recorded `void_reason`, and is excluded from the sum."

        Design: Difficulty/compensating_invariant/ancillary_obligation_void_restores_obligated_cents_ledger
        """
        booking, _, _, seat_obligation = _cascade_with_two_ancillary_obligations(api)
        before = read_booking(api, booking["id"])
        assert_booking_ledger(before, total_refund_obligated_cents=106400)

        void(api, seat_obligation["id"], "CREATED_IN_ERROR")

        voided = read_obligation(api, seat_obligation["id"])
        assert_obligation_axes(voided, settlement_status="VOIDED")
        assert voided["void_reason"] == "CREATED_IN_ERROR"
        assert_obligation_amounts(voided, amount_cents=4500)
        after = read_booking(api, booking["id"])
        assert_booking_ledger(
            after,
            total_refund_obligated_cents=101900,
            collected_total_cents=106400,
            disruption_posture="REFUND_OBLIGATED",
            suppressed_obligation_count=0,
        )
        assert_instant(after["earliest_refund_deadline_utc"], "2026-08-17T18:00:00Z")
        assert_obligated_ledger(after, list_obligations(api, booking["id"]))

    def test_the_void_reopens_only_the_purchase_it_named(self, api):
        """The seat returns to pending delivery; the entertainment charge is untouched.

        PRD §3.3: "When an obligation on an `ANCILLARY` basis is voided for the reason
        `CREATED_IN_ERROR`, the purchase it named returns `NOT_PROVIDED →
        PENDING_DELIVERY`, its `non_provision_reason` is cleared to null, its
        `refund_obligation_created` returns to false, and its `version` advances by 1."

        Design: Difficulty/compensating_invariant/ancillary_obligation_void_restores_obligated_cents_ledger
        """
        _, seat, entertainment, seat_obligation = _cascade_with_two_ancillary_obligations(
            api
        )

        void(api, seat_obligation["id"], "CREATED_IN_ERROR")

        restored = read_ancillary(api, seat["id"])
        assert restored["delivery_status"] == "PENDING_DELIVERY"
        assert_null(restored["non_provision_reason"], "non_provision_reason")
        assert restored["refund_obligation_created"] is False

        untouched = read_ancillary(api, entertainment["id"])
        assert untouched["delivery_status"] == "NOT_PROVIDED"
        assert untouched["refund_obligation_created"] is True


# ─── Reversing a travel-credit settlement ─────────────


def _settled_travel_credit_obligation(api):
    """An 80000-cent refund taken as travel credit and paid out in full."""
    set_clock(api, "2026-08-10T18:00:00Z")
    world = build_world(
        api,
        total_fare_cents=80000,
        segment_fares=[80000],
        record_locator="CRD001",
        email="credit@example.com",
    )
    cancel_segment(api, world.segments[0]["id"], "2026-08-10T18:00:00Z")
    obligation = sole_obligation(api, world.booking["id"])
    elect(api, obligation["id"], "TRAVEL_CREDIT", world.passenger_headers)
    initiate(api, obligation["id"], OFFICER_2_HEADERS)
    complete(api, obligation["id"], OFFICER_3_HEADERS, outcome="SUCCEEDED")
    world.obligation = read_obligation(api, obligation["id"])
    return world


class TestCreditSettlementReversal:
    def test_settling_as_travel_credit_credits_the_bonus_into_the_balance(self, api):
        """A tenth of the principal rides along into the passenger's credit balance.

        PRD §3.7: "Electing `TRAVEL_CREDIT` sets `election_status` to `ELECTED_CREDIT`
        and `settlement_method` to `TRAVEL_CREDIT`, and adds the goodwill bonus:
        `credit_bonus_cents` is the obligation's `amount_cents` multiplied by the profile's
        `travel_credit_election_bonus_pct` and rounded half up — one tenth of the principal
        under the regulatory default — and `payable_total_cents` becomes `amount_cents` plus
        that bonus."

        PRD §3.7: "A `SUCCEEDED` outcome moves the axis `INITIATED → SETTLED`, stamps
        `settled_at_utc` from the logical clock, and advances the obligation's `version` by
        1; when the `settlement_method` is `TRAVEL_CREDIT`, the passenger's
        `travel_credit_balance_cents` grows by the obligation's `payable_total_cents` —
        bonus included — and the passenger's `version` advances by 1."

        Design: Difficulty/compensating_invariant/credit_settlement_reversal_restores_travel_credit_balance
        """
        world = _settled_travel_credit_obligation(api)

        assert_obligation_amounts(
            world.obligation,
            amount_cents=80000,
            credit_bonus_cents=8000,
            payable_total_cents=88000,
        )
        assert_obligation_axes(
            world.obligation,
            election_status="ELECTED_CREDIT",
            election_source="PASSENGER",
            settlement_method="TRAVEL_CREDIT",
            settlement_status="SETTLED",
        )
        passenger = read_passenger(api, world.passenger["id"])
        assert passenger["travel_credit_balance_cents"] == 88000
        assert_booking_ledger(
            read_booking(api, world.booking["id"]),
            total_refund_obligated_cents=80000,
            disruption_posture="CLOSED_OUT",
        )

    def test_reversing_the_settlement_puts_the_balance_back_to_zero(self, api):
        """The bonus comes back out too, and the settled instant is kept for audit.

        PRD §2.11: "Here too the symmetry is exact: a credit obligation that is settled
        and then reversed leaves the balance at precisely its pre-settlement value,
        including the goodwill bonus portion."

        PRD §3.7: "And a `SETTLEMENT_REVERSED` void of an obligation settled as travel
        credit subtracts the obligation's `payable_total_cents` back out of the passenger's
        `travel_credit_balance_cents` and advances the passenger's `version` by 1, leaving
        the balance at precisely its pre-settlement value; the obligation's
        `settled_at_utc` is retained for audit rather than cleared."

        Design: Difficulty/compensating_invariant/credit_settlement_reversal_restores_travel_credit_balance
        """
        world = _settled_travel_credit_obligation(api)

        void(api, world.obligation["id"], "SETTLEMENT_REVERSED")

        reversed_row = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(reversed_row, settlement_status="VOIDED")
        assert reversed_row["void_reason"] == "SETTLEMENT_REVERSED"
        assert reversed_row["settled_at_utc"] is not None, (
            "the settled instant is retained for audit"
        )
        passenger = read_passenger(api, world.passenger["id"])
        assert passenger["travel_credit_balance_cents"] == 0
        assert_travel_credit_ledger(passenger, list_obligations(api, world.booking["id"]))
        booking = read_booking(api, world.booking["id"])
        assert_booking_ledger(
            booking, total_refund_obligated_cents=0, disruption_posture="DISRUPTED"
        )
        assert_null(booking["earliest_refund_deadline_utc"], "earliest_refund_deadline_utc")
