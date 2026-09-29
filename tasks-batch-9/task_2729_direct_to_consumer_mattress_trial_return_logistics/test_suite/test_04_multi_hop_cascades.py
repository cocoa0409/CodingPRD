"""Single writes whose contractual effects reach three and four entities deep.

The deepest hop of each cascade is asserted, because an implementation that
stops at the first entity still passes a shallow test.
"""

from test_helpers import (
    approve_comfort_exchange,
    assert_instant,
    book_appointment,
    complete_appointment,
    create_customer_row,
    create_model,
    file_quality_claim,
    open_return_case,
    preload_abuse_signals,
    read_customer,
    read_order,
    read_quality_claim,
    read_return_case,
    read_route,
    request_comfort_exchange,
    set_clock,
    setup_delivered_order,
    setup_published_route,
)


class TestPickupCompletionCascadesFourHopsIntoTheCustomerBlock:
    """A collection on night 24 for a customer already carrying 65 rolling points."""

    def _completed_pickup(self):
        model = create_model(sku="MDL-Q-MED-K", name="Comfort Q Medium")
        customer = create_customer_row(
            email="tc1@example.com", full_name="Tobin Cascade", household_hash="HH-TC1"
        )
        preload_abuse_signals(
            customer["id"],
            [
                ("HOUSEHOLD_MATCH", "2026-07-01T00:00:00Z"),
                ("REPEAT_RETURN", "2026-07-01T00:00:00Z"),
                ("MULTI_CHANNEL", "2026-07-01T00:00:00Z"),
            ],
        )
        scenario = setup_delivered_order(model=model, customer=customer)
        case = open_return_case(
            scenario["order"]["id"],
            scenario["customer_headers"],
            requested_at="2026-08-22T00:00:00Z",
        )
        route = setup_published_route(
            route_date="2026-08-25",
            window_start_at="2026-08-25T08:00:00Z",
            window_end_at="2026-08-25T18:00:00Z",
            capacity_units=6,
        )
        appointment = book_appointment(
            route["id"],
            case["id"],
            slot_start_at="2026-08-25T09:00:00Z",
            slot_end_at="2026-08-25T11:00:00Z",
        )
        scenario["return_case"] = case
        scenario["route"] = route
        scenario["appointment"] = complete_appointment(
            appointment["id"], "COMPLETED", at="2026-08-25T00:00:00Z"
        )
        return scenario

    def test_the_first_two_hops_close_the_case_and_the_order_on_night_twenty_four(self):
        """PRD §3.7: "Hop one moves the return case `PICKUP_SCHEDULED → PICKED_UP`, stamps `picked_up_at` from the logical clock, and computes `nights_used` as the whole number of complete days between the order's `delivered_at` and `picked_up_at` — this is the proration basis both refund variants will read."

        Delivery on 2026-08-01 and collection on 2026-08-25 is 24 complete days,
        and hop two freezes the order's `nights_slept` at that same figure while
        closing both of its axes.

        Design: Difficulty/transitive_cascade/pickup_completion_cascades_four_hops_into_customer_block
        """
        scenario = self._completed_pickup()

        appointment = scenario["appointment"]
        assert appointment["status"] == "COMPLETED"
        assert_instant(appointment["closed_at"], "2026-08-25T00:00:00Z", "closed_at")

        case = read_return_case(scenario["return_case"]["id"])
        assert case["logistics_status"] == "PICKED_UP"
        assert_instant(case["picked_up_at"], "2026-08-25T00:00:00Z", "picked_up_at")
        assert case["nights_used"] == 24, (
            f"nights_used is the 24 complete days of use, got {case['nights_used']}"
        )

        order = read_order(scenario["order"]["id"])
        assert order["trial_status"] == "RETURNED"
        assert order["fulfillment_status"] == "CLOSED"
        assert order["nights_slept"] == 24

    def test_the_last_two_hops_append_a_short_trial_signal_and_block_the_customer(self):
        """PRD §3.7: "Hop three, because the order has entered `RETURNED`, increments the customer's `completed_return_count` by one and appends abuse signals — a `REPEAT_RETURN` signal when `completed_return_count` was already at least one *before* this increment, and additionally a `SHORT_TRIAL` signal when the case's `nights_used` is fewer than 30 nights."

        The counter was zero before the increment so no REPEAT_RETURN is
        appended, but 24 nights is under thirty so a fourth signal worth 15
        points arrives, taking the rolling score from 65 to exactly 80 and
        setting a block one year out from the collection instant.

        Design: Difficulty/transitive_cascade/pickup_completion_cascades_four_hops_into_customer_block
        """
        scenario = self._completed_pickup()
        customer = read_customer(scenario["customer"]["id"])

        assert customer["completed_return_count"] == 1
        assert customer["signal_count"] == 4, (
            "only a SHORT_TRIAL signal is appended on a first completed return, "
            f"got {customer['signal_count']} signals"
        )
        assert customer["abuse_score_rolling"] == 80
        assert customer["abuse_score_lifetime"] == 80
        assert customer["status"] == "BLOCKED"
        assert_instant(
            customer["trial_block_until"], "2027-08-25T00:00:00Z", "trial_block_until"
        )

    def test_a_completed_slot_keeps_consuming_the_route_capacity_it_used(self):
        """PRD §2.10: "A slot that is cancelled or closed as missed returns its units to the pool, because those two statuses are excluded from the sum; a slot that is completed keeps consuming its units forever, because the truck did in fact carry the mattress."

        The QUEEN collection consumed two of the route's six units and the
        completion leaves them consumed.

        Design: Difficulty/transitive_cascade/pickup_completion_cascades_four_hops_into_customer_block
        """
        scenario = self._completed_pickup()
        route = read_route(scenario["route"]["id"])

        assert route["booked_units"] == 2
        assert route["available_units"] == 4


class TestExchangeApprovalCascadesThreeHops:
    """An approval that mints a replacement and unwinds an open compression complaint."""

    def _approved_exchange(self):
        medium = create_model(
            sku="MDL-Q-MED-E", firmness="MEDIUM", size="QUEEN", list_price_cents=120000
        )
        firm = create_model(
            sku="MDL-Q-FIRM-E", firmness="FIRM", size="QUEEN", list_price_cents=139000
        )
        scenario = setup_delivered_order(
            model=medium,
            customer_overrides={"email": "tc2@example.com", "household_hash": "HH-TC2"},
        )
        set_clock("2026-08-05T00:00:00Z")
        claim = file_quality_claim(
            scenario["order"]["id"],
            "COMPRESSION_RECOVERY",
            2,
            headers=scenario["customer_headers"],
        )
        set_clock("2026-08-22T00:00:00Z")
        exchange = request_comfort_exchange(
            scenario["order"]["id"], firm["id"], headers=scenario["customer_headers"]
        )
        scenario["target_model"] = firm
        scenario["claim"] = claim
        scenario["exchange"] = approve_comfort_exchange(
            exchange["id"], scenario["order"]["id"]
        )
        return scenario

    def test_hop_one_mints_a_replacement_order_one_link_deeper_in_the_chain(self):
        """PRD §3.5: "Hop one mints the replacement trial order: its `model_id` is the exchange's `target_model_id`, its `gross_price_cents` is that target model's `list_price_cents`, its `bundle_id` is null, its `channel` and `retail_partner_id` are copied from the original order, its `exchanged_from_order_id` points at the `original_order_id`, its `exchange_chain_depth` is one greater than the original's, and it opens at `fulfillment_status` `CREATED` and `trial_status` `NOT_STARTED`."

        The replacement is quoted at the FIRM model's 139000-cent list price and
        has to be dispatched and delivered like any other order.

        Design: Difficulty/transitive_cascade/exchange_approval_cascades_three_hops_and_withdraws_open_compression_claim
        """
        scenario = self._approved_exchange()
        replacement = read_order(scenario["exchange"]["replacement_order_id"])

        assert replacement["model_id"] == scenario["target_model"]["id"]
        assert replacement["exchanged_from_order_id"] == scenario["order"]["id"]
        assert replacement["exchange_chain_depth"] == 1
        assert replacement["fulfillment_status"] == "CREATED"
        assert replacement["trial_status"] == "NOT_STARTED"
        assert replacement["gross_price_cents"] == 139000
        assert replacement["bundle_id"] is None

    def test_hops_two_and_three_retire_the_original_and_withdraw_the_complaint(self):
        """PRD §3.5: "Hop three unwinds those complaints: because the original order has entered `EXCHANGED`, every quality claim on it whose `claim_type` is `COMPRESSION_RECOVERY` and whose `status` is `SUBMITTED` or `EVIDENCE_REQUESTED` is moved to `WITHDRAWN` with `resolution` `DENIED`."

        The original order leaves DAMAGED_REPORTED for REPLACED with its trial
        axis at EXCHANGED, the exchange settles at 19000 + 9900 = 28900 cents
        owed by the customer, and the open complaint is withdrawn rather than
        paid.

        Design: Difficulty/transitive_cascade/exchange_approval_cascades_three_hops_and_withdraws_open_compression_claim
        """
        scenario = self._approved_exchange()

        exchange = scenario["exchange"]
        assert exchange["status"] == "APPROVED"
        assert exchange["price_difference_cents"] == 28900
        assert exchange["settlement_direction"] == "CHARGE_CUSTOMER"

        original = read_order(scenario["order"]["id"])
        assert original["fulfillment_status"] == "REPLACED"
        assert original["trial_status"] == "EXCHANGED"

        claim = read_quality_claim(scenario["claim"]["id"])
        assert claim["status"] == "WITHDRAWN"
        assert claim["resolution"] == "DENIED"
        assert claim["credit_cents"] == 0
