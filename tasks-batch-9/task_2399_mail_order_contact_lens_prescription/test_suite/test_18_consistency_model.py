"""Read-your-write consistency: the write response and the very next read
already carry every derived consequence of the call.

Each test builds its own world from an empty database and pins the logical clock
before any deadline-sensitive step.
"""

from test_helpers import (
    CO_ALPHA_HEADERS,
    FO_HEADERS,
    WORKING_TUESDAY_10AM,
    assert_ledger_values,
    create_order_payload,
    get_ledger,
    make_customer_headers,
    make_prescriber_headers,
    new_order,
    set_clock,
    setup_verification_round,
    setup_verified_prescription,
    validate_paginated,
    validate_success,
)


class TestOrderCreationIsImmediatelyConsistent:
    """Placing an order prices itself and moves both ledgers in the same call."""

    def test_order_creation_response_carries_the_snapshots_and_the_priced_totals(
        self, api
    ):
        """PRD §3.5: "The ordered product's `unit_price_cents` and
        `lenses_per_box` are copied onto the order as `unit_price_cents` and
        `lenses_per_box_at_capture`, and `fulfilled_product_id` is initialised to
        the same value as `ordered_product_id`."

        PRD §3.5: "`subtotal_cents` is the snapshotted `unit_price_cents`
        multiplied by total boxes."

        PRD §3.5: "`shipping_cents` is zero when `subtotal_cents` has reached the
        free-shipping threshold of 5,000 cents — fifty dollars, and the
        comparison is inclusive, so a subtotal of exactly 5,000 cents ships free
        — and is otherwise the flat standard charge of 695 cents."

        PRD §3.5: "`total_cents` is `subtotal_cents` plus `shipping_cents`."

        Design: Corner/consistency_model/order_creation_response_already_carries_the_recomputed_totals
        """
        scenario = setup_verified_prescription(clock="2026-08-01T00:00:00Z")
        customer_id = scenario["customer"]["id"]

        created = validate_success(
            api.create_order(
                create_order_payload(
                    customer_id,
                    scenario["prescription"]["id"],
                    scenario["product"]["id"],
                    1,
                    1,
                ),
                make_customer_headers(customer_id),
            ),
            201,
        )

        assert created["unit_price_cents"] == 3200
        assert created["lenses_per_box_at_capture"] == 30
        assert created["subtotal_cents"] == 6400
        assert created["shipping_cents"] == 0
        assert created["total_cents"] == 6400

    def test_ledger_and_box_counter_are_visible_on_the_very_next_read(self, api):
        """PRD §3.5: "Placing an order also moves the ledgers forward: the
        prescription's `boxes_consumed` grows by the ordered boxes, and the
        customer's `lifetime_charged_cents` and `net_cash_position_cents` are
        reconciled."

        PRD §2.7: "`lifetime_charged_cents` is the sum of `total_cents` over
        every order of that customer whose `fulfillment_state` is anything other
        than `CANCELLED`."

        PRD §2.7: "`net_cash_position_cents` is `lifetime_charged_cents` less
        `lifetime_refunded_cents`."

        PRD §2.7: "`boxes_consumed` is the sum of `boxes_od` plus `boxes_os` over
        every order against that prescription whose `fulfillment_state` is not
        `CANCELLED`; this is the box invariant, **INV_BOXES**."

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object, where `total_count` counts every
        row matching the filters before pagination is applied and `has_more` is
        true when rows remain beyond the returned page."

        Design: Corner/consistency_model/order_creation_response_already_carries_the_recomputed_totals
        """
        scenario = setup_verified_prescription(clock="2026-08-01T00:00:00Z")
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]

        order = new_order(
            customer_id, prescription_id, scenario["product"]["id"], 1, 1
        )

        assert_ledger_values(
            get_ledger(customer_id),
            lifetime_charged_cents=6400,
            net_cash_position_cents=6400,
        )

        prescription = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert prescription["boxes_consumed"] == 2

        orders, meta = validate_paginated(
            api.list_orders(CO_ALPHA_HEADERS, params={"customer_id": customer_id})
        )
        assert meta["total_count"] == 1
        assert orders[0]["id"] == order["id"]


class TestConfirmedResponseIsImmediatelyConsistent:
    """One CONFIRMED response clears every pending order before it returns."""

    def test_confirmed_response_clears_both_pending_orders_in_the_same_call(self, api):
        """PRD §3.4: "A `CONFIRMED` response sets the request's `status` and
        `response_type` both to `CONFIRMED` and promotes the prescription from
        `PENDING_VERIFICATION` to `VERIFIED_ACTIVE`."

        PRD §3.4: "Every order against that prescription whose
        `verification_state` is `RX_PENDING` then moves to `RX_CLEARED`,
        processed in `created_at` ascending order, each of those orders
        contributing its own `RESPONSE_RECEIVED` compliance event with
        `subject_type` `Order`."

        PRD §3.5: "Its `verification_state` is seeded from the prescription:
        `RX_CLEARED` when the prescription is already `VERIFIED_ACTIVE`, and
        `RX_PENDING` otherwise."

        PRD §3.4: "Every verification request still in `SENT` whose
        `passive_deadline_at` has been reached, meaning the current logical time
        is at or after it, moves to the terminal `PASSIVE_TIMEOUT` with
        `response_type` left null."

        Design: Corner/consistency_model/confirmed_response_clears_pending_orders_within_the_same_call
        """
        scenario = setup_verification_round(clock=WORKING_TUESDAY_10AM)
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        prescriber_id = scenario["prescriber"]["id"]
        product_id = scenario["product"]["id"]

        first_order = new_order(customer_id, prescription_id, product_id, 1, 1)
        second_order = new_order(customer_id, prescription_id, product_id, 2, 1)
        assert first_order["verification_state"] == "RX_PENDING"
        assert second_order["verification_state"] == "RX_PENDING"

        set_clock("2026-09-08T12:00:00Z")

        confirmed = validate_success(
            api.respond_to_verification_request(
                scenario["verification_request"]["id"],
                {"response_type": "CONFIRMED"},
                make_prescriber_headers(prescriber_id),
            )
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["response_type"] == "CONFIRMED"

        prescription = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert prescription["status"] == "VERIFIED_ACTIVE"
        assert prescription["boxes_consumed"] == 5

        _, cleared_meta = validate_paginated(
            api.list_orders(
                FO_HEADERS,
                params={
                    "prescription_id": prescription_id,
                    "verification_state": "RX_CLEARED",
                },
            )
        )
        assert cleared_meta["total_count"] == 2

        _, pending_meta = validate_paginated(
            api.list_orders(
                FO_HEADERS,
                params={
                    "prescription_id": prescription_id,
                    "verification_state": "RX_PENDING",
                },
            )
        )
        assert pending_meta["total_count"] == 0

        sweep = validate_success(api.run_verification_sweep(CO_ALPHA_HEADERS))
        assert sweep["promoted_prescription_ids"] == []
        assert sweep["timed_out_request_ids"] == []
