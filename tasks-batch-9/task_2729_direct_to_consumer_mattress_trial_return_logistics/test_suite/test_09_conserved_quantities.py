"""Reversals that must restore a conserved quantity to its exact prior value.

One rule conserves the order's four-way money identity across a release and its
claw-back; the other conserves a route's capacity ledger across a cancellation
and a missed visit.
"""

from test_helpers import (
    LOGISTICS,
    api_client,
    assert_instant,
    assert_refund_ledger_identity,
    assert_route_capacity_identity,
    book_appointment,
    complete_appointment,
    create_model,
    get_success_data,
    make_finance_controller_headers,
    open_return_case,
    read_appointment,
    read_order,
    read_return_case,
    read_route,
    release_refund,
    set_clock,
    setup_delivered_order,
    setup_published_route,
    setup_return_lifecycle,
    validate_paginated,
    void_refund,
)

AUTHORIZER_4 = make_finance_controller_headers("fin-authorizer-4")
RELEASER_4 = make_finance_controller_headers("fin-releaser-4")


class TestReleaseThenVoidConservesThePaidAmountLedger:
    """A 114000-cent refund released and then clawed back on a 120000-cent order."""

    def _authorized_refund(self):
        return setup_return_lifecycle(
            stage="AUTHORIZED",
            model_overrides={"sku": "MDL-Q-MED-C1", "donation_eligible": True},
            customer_overrides={
                "email": "ci1@example.com",
                "full_name": "Cora Invariant",
                "household_hash": "HH-CI1",
            },
            authorizer_headers=AUTHORIZER_4,
        )

    def test_release_rewrites_all_three_movable_ledger_fields_at_once(self):
        """PRD §3.9: "Release advances the row `AUTHORIZED → RELEASED`, records `released_by_user_id` and stamps `released_at` from the logical clock, and then rewrites the order's ledger so the four-way identity of section 2.9 still holds: `net_refund_cents` is added to `refunded_total_cents`, `outstanding_refundable_cents` is set to zero, and `retained_amount_cents` is set to `paid_amount_cents` less `refunded_total_cents`."

        Before the release the whole 120000-cent principal is outstanding; after
        it 114000 is refunded, nothing is outstanding and the 6000-cent
        proration is retained.

        Design: Difficulty/compensating_invariant/refund_release_then_void_conserves_the_paid_amount_ledger_identity
        """
        scenario = self._authorized_refund()

        before = read_order(scenario["order"]["id"])
        assert before["refunded_total_cents"] == 0
        assert before["outstanding_refundable_cents"] == 120000
        assert before["retained_amount_cents"] == 0
        assert_refund_ledger_identity(before)

        released = release_refund(scenario["refund"]["id"], headers=RELEASER_4)
        assert released["status"] == "RELEASED"
        assert_instant(released["released_at"], "2026-09-15T00:00:00Z", "released_at")

        after = read_order(scenario["order"]["id"])
        assert after["refunded_total_cents"] == 114000
        assert after["outstanding_refundable_cents"] == 0
        assert after["retained_amount_cents"] == 6000
        assert_refund_ledger_identity(after)
        assert read_return_case(scenario["return_case"]["id"])["financial_status"] == "RELEASED"

    def test_voiding_the_released_refund_restores_the_ledger_exactly(self):
        """PRD §3.9: "Voiding a `RELEASED` row stamps `voided_at`, moves the case's money axis `RELEASED → VOID`, and performs the exact compensating reversal: `net_refund_cents` is subtracted from the order's `refunded_total_cents`, `outstanding_refundable_cents` is restored to `paid_amount_cents` less `refunded_total_cents`, and `retained_amount_cents` returns to zero once `refunded_total_cents` has come back to zero."

        The claw-back returns the triple to 0 / 120000 / 0, the ledger row keeps
        its 114000-cent net figure as an audit record, and the logistics axis of
        the case never moves off DISPOSITIONED.

        Design: Difficulty/compensating_invariant/refund_release_then_void_conserves_the_paid_amount_ledger_identity
        """
        scenario = self._authorized_refund()
        release_refund(scenario["refund"]["id"], headers=RELEASER_4)
        voided = void_refund(
            scenario["refund"]["id"],
            headers=RELEASER_4,
            void_reason="customer disputed the proration and the release was reversed",
        )

        assert voided["status"] == "VOIDED"
        assert voided["net_refund_cents"] == 114000
        assert_instant(voided["voided_at"], "2026-09-15T00:00:00Z", "voided_at")

        order = read_order(scenario["order"]["id"])
        assert order["refunded_total_cents"] == 0
        assert order["outstanding_refundable_cents"] == 120000
        assert order["retained_amount_cents"] == 0
        assert_refund_ledger_identity(order)

        case = read_return_case(scenario["return_case"]["id"])
        assert case["financial_status"] == "VOID"
        assert case["logistics_status"] == "DISPOSITIONED"
        assert case["final_refund_cents"] == 114000

        _rows, meta = validate_paginated(
            api_client.list_refund_authorizations(
                make_finance_controller_headers("fin-reader-4"),
                params={"return_case_id": scenario["return_case"]["id"]},
            )
        )
        assert meta["total_count"] == 1, (
            f"voiding must not mint a second ledger row, got {meta['total_count']}"
        )


class TestCancelAndMissedConserveRouteCapacityUnits:
    """Two slots on a six-unit route, released by the two non-consuming closeouts."""

    def _route_with_two_booked_slots(self):
        queen = create_model(sku="MDL-Q-C2", size="QUEEN", list_price_cents=120000)
        twin = create_model(
            sku="MDL-T-C2", size="TWIN", name="Guest Twin Medium", list_price_cents=70000
        )
        first = setup_delivered_order(
            model=queen,
            customer_overrides={
                "email": "ci2a@example.com",
                "full_name": "Cap Conserve",
                "household_hash": "HH-CI2A",
            },
            order_overrides={"gross_price_cents": 120000},
        )
        second = setup_delivered_order(
            model=twin,
            customer_overrides={
                "email": "ci2b@example.com",
                "full_name": "Tina Conserve",
                "household_hash": "HH-CI2B",
            },
            order_overrides={"gross_price_cents": 70000},
        )

        set_clock("2026-09-10T00:00:00Z")
        case_one = open_return_case(first["order"]["id"], first["customer_headers"])
        case_two = open_return_case(second["order"]["id"], second["customer_headers"])

        route = setup_published_route(capacity_units=6)
        appointment_one = book_appointment(
            route["id"],
            case_one["id"],
            slot_start_at="2026-09-15T09:00:00Z",
            slot_end_at="2026-09-15T10:00:00Z",
            expected_version=route["version"],
        )
        after_first = read_route(route["id"])
        appointment_two = book_appointment(
            route["id"],
            case_two["id"],
            slot_start_at="2026-09-15T11:00:00Z",
            slot_end_at="2026-09-15T12:00:00Z",
            expected_version=after_first["version"],
        )
        return {
            "queen_order": first["order"],
            "twin_order": second["order"],
            "case_one": case_one,
            "case_two": case_two,
            "route": route,
            "appointment_one": appointment_one,
            "appointment_two": appointment_two,
        }

    def test_cancelling_and_missing_the_two_slots_returns_every_unit_to_the_pool(self):
        """PRD §2.10: "A slot that is cancelled or closed as missed returns its units to the pool, because those two statuses are excluded from the sum; a slot that is completed keeps consuming its units forever, because the truck did in fact carry the mattress."

        The six-unit route runs 0+6 → 2+4 after the queen slot → 3+3 after the
        twin slot → 1+5 once the queen slot is cancelled → 0+6 once the twin slot
        is closed as missed, and the capacity identity holds at every instant.

        Design: Difficulty/compensating_invariant/appointment_cancel_and_missed_conserve_route_capacity_units
        """
        scenario = self._route_with_two_booked_slots()
        route_id = scenario["route"]["id"]

        both_booked = read_route(route_id)
        assert both_booked["capacity_units"] == 6
        assert both_booked["booked_units"] == 3, (
            f"a 2-unit queen slot and a 1-unit twin slot consume 3 units, got "
            f"{both_booked['booked_units']}"
        )
        assert both_booked["available_units"] == 3
        assert_route_capacity_identity(both_booked)

        cancelled = get_success_data(
            api_client.cancel_pickup_appointment(
                scenario["appointment_one"]["id"], {}, LOGISTICS
            )
        )
        assert cancelled["status"] == "CANCELLED"
        after_cancel = read_route(route_id)
        assert after_cancel["booked_units"] == 1, (
            "cancelling the 2-unit queen slot must hand its units straight back, "
            f"got {after_cancel['booked_units']}"
        )
        assert after_cancel["available_units"] == 5
        assert_route_capacity_identity(after_cancel)

        missed = complete_appointment(
            scenario["appointment_two"]["id"], "MISSED", at="2026-09-15T12:30:00Z"
        )
        assert missed["status"] == "MISSED"
        after_missed = read_route(route_id)
        assert after_missed["booked_units"] == 0, (
            "a missed visit consumed no capacity, so the route must be back to "
            f"empty, got {after_missed['booked_units']}"
        )
        assert after_missed["available_units"] == 6
        assert_route_capacity_identity(after_missed)

    def test_neither_closeout_prices_anything_on_its_return_case(self):
        """PRD §3.7: "An `outcome` of `MISSED` — nobody home, or the crew ran out of daylight — advances the appointment `BOOKED → MISSED`, stamps `closed_at` from the logical clock, subtracts the slot's `units` from the route's `booked_units` so `available_units` is restored, reverts the return case `PICKUP_SCHEDULED → REQUESTED`, and bumps the route's `version`."

        Both cases land back in REQUESTED with no pickup instant and no usage
        count, the missed slot records its closeout instant while the cancelled
        one records none, and neither order leaves RETURN_REQUESTED.

        Design: Difficulty/compensating_invariant/appointment_cancel_and_missed_conserve_route_capacity_units
        """
        scenario = self._route_with_two_booked_slots()

        get_success_data(
            api_client.cancel_pickup_appointment(
                scenario["appointment_one"]["id"], {}, LOGISTICS
            )
        )
        complete_appointment(
            scenario["appointment_two"]["id"], "MISSED", at="2026-09-15T12:30:00Z"
        )

        cancelled = read_appointment(scenario["appointment_one"]["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["closed_at"] is None, (
            "a cancelled slot records no closed_at — the difference between the "
            f"two branches is only in the audit trail, got {cancelled['closed_at']}"
        )

        missed = read_appointment(scenario["appointment_two"]["id"])
        assert missed["status"] == "MISSED"
        assert_instant(missed["closed_at"], "2026-09-15T12:30:00Z", "closed_at")

        case_one = read_return_case(scenario["case_one"]["id"])
        assert case_one["logistics_status"] == "REQUESTED"
        assert case_one["picked_up_at"] is None
        assert case_one["nights_used"] is None

        case_two = read_return_case(scenario["case_two"]["id"])
        assert case_two["logistics_status"] == "REQUESTED"
        assert case_two["nights_used"] is None, (
            "nothing is priced until the mattress is actually collected, so a "
            f"missed visit leaves nights_used null, got {case_two['nights_used']}"
        )

        assert read_order(scenario["queen_order"]["id"])["trial_status"] == "RETURN_REQUESTED"
        assert read_order(scenario["twin_order"]["id"])["trial_status"] == "RETURN_REQUESTED"

    def test_the_freed_units_can_be_rebooked_on_the_same_route(self):
        """PRD §3.7: "Either way the return case is back in `REQUESTED` and may be rebooked on any published route, which makes the logistics axis a cycle: `REQUESTED → PICKUP_SCHEDULED → REQUESTED`."

        With both slots released the queen case re-books its original 09:00 slot
        and consumes exactly the same 2 units it consumed the first time, taking
        the route from 0+6 back to 2+4.

        Design: Difficulty/compensating_invariant/appointment_cancel_and_missed_conserve_route_capacity_units
        """
        scenario = self._route_with_two_booked_slots()
        route_id = scenario["route"]["id"]

        get_success_data(
            api_client.cancel_pickup_appointment(
                scenario["appointment_one"]["id"], {}, LOGISTICS
            )
        )
        complete_appointment(
            scenario["appointment_two"]["id"], "MISSED", at="2026-09-15T12:30:00Z"
        )

        emptied = read_route(route_id)
        rebooked = book_appointment(
            route_id,
            scenario["case_one"]["id"],
            slot_start_at="2026-09-15T09:00:00Z",
            slot_end_at="2026-09-15T10:00:00Z",
            expected_version=emptied["version"],
        )

        assert rebooked["status"] == "BOOKED"
        assert rebooked["units"] == 2
        assert rebooked["closed_at"] is None

        final = read_route(route_id)
        assert final["booked_units"] == 2, (
            "the released capacity must be genuinely reusable, not merely "
            f"reported free, got {final['booked_units']}"
        )
        assert final["available_units"] == 4
        assert_route_capacity_identity(final)
        assert read_return_case(scenario["case_one"]["id"])["logistics_status"] == "PICKUP_SCHEDULED"
