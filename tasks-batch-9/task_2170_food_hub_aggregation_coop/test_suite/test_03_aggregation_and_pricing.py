"""Aggregation: the cross-producer allocation waterfall, the margin tier that
keys on the pre-margin subtotal, per-allocation rounding and the credit gate."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    add_order_line,
    allocations_for_line,
    allocations_for_product,
    assert_allocation,
    assert_allocation_money_split,
    assert_buyer_order,
    assert_order_total_identity,
    create_buyer,
    create_buyer_payload,
    create_draft_order,
    create_listed_product,
    create_order_line_payload,
    make_buyer_headers,
    onboard_active_producer,
    read_order,
    read_order_line,
    read_product,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDemandCapture:
    def test_an_unrecognised_buyer_type_is_a_malformed_request(self, api):
        """PRD 3.4: "An institutional buyer is registered by hub operations with
        a `legal_name` of 1 to 120 non-blank characters, a `buyer_type` of
        `SCHOOL_DISTRICT`, `HOSPITAL`, `UNIVERSITY` or `CORRECTIONS`, a
        `dock_zone_code` of 1 to 12 characters naming the receiving dock the
        routing team plans against, a `payment_terms_days` that must be exactly
        15, 30 or 45, and a `credit_limit_cents` of at least 0."
        PRD 2.8: "Request shape — required body fields present, enum values
        legal, numbers inside their declared ranges, datetimes parseable as ISO
        8601 UTC, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/buyer_type_invalid_enum_value_is_rejected
        """
        payload = create_buyer_payload(
            legal_name="Riverside Council",
            buyer_type="MUNICIPALITY",
            dock_zone_code="Z9",
            credit_limit_cents=100000,
        )
        resp = api.create_buyer(payload, HUB)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_adding_a_line_to_an_unknown_order_reports_order_not_found(self, api):
        """PRD 2.4: "When a URL names a parent and then a child, the parent id is
        looked up first: if a producer id in the path does not resolve, the
        request fails with `ERR_PRODUCER_NOT_FOUND` before the request body is
        examined at all, and the same holds for every other path segment with
        its own matching not-found code — `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_DOCK_SLOT_NOT_FOUND`,
        `ERR_APPOINTMENT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND` and `ERR_CYCLE_NOT_FOUND`."

        Design: Corner/entities/order_line_creation_under_unknown_parent_order_returns_not_found
        """
        set_clock(CLOCK_BASE)
        buyer = create_buyer()
        resp = api.create_order_line(
            "00000000-0000-4000-8000-000000000000",
            create_order_line_payload(quantity_requested=10),
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)


class TestAllocationWaterfall:
    def _two_producers_with_priced_supply(self, first_price, second_price,
                                          offered=10):
        set_clock(CLOCK_BASE)
        first = onboard_active_producer()
        second = onboard_active_producer(
            legal_name="Stony Creek Dairy",
            region_code="ALL",
            contact_email="sc@example.org",
            verifier_user_id="co-verify-2",
            approver_user_id="co-approve-8",
        )
        product_one = create_listed_product(
            first["producer_id"],
            quantity_offered=offered,
            producer_unit_price_cents=first_price,
        )
        product_two = create_listed_product(
            second["producer_id"],
            quantity_offered=offered,
            producer_unit_price_cents=second_price,
        )
        return first, second, product_one, product_two

    def test_the_waterfall_draws_from_the_cheapest_item_first(self, api):
        """PRD 3.5: "Candidates are then ranked, and the ranking is applied in
        exactly this sequence: cheapest `producer_unit_price_cents` first; among
        items at the same price, the producer with the smaller
        `patronage_volume_cents` first, which is how the cooperative spreads
        business toward members who have sold less through the hub; and among
        those still tied, the item created earlier first."
        PRD 3.5: "Walking that ranking, the system draws from each item in turn
        while the line still has unfilled units, taking the smaller of the units
        still needed and the item's `quantity_available`."

        Design: Corner/calculations/allocation_selector_ranks_cheapest_producer_price_first
        """
        _, _, product_one, product_two = self._two_producers_with_priced_supply(
            1800, 1700
        )
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=15)

        validate_success(api.aggregate_order(order["id"], HUB))

        cheap = allocations_for_product(product_two["id"])[0]
        dear = allocations_for_product(product_one["id"])[0]
        assert cheap["quantity"] == 10
        assert cheap["producer_unit_price_cents"] == 1700
        assert dear["quantity"] == 5
        assert dear["producer_unit_price_cents"] == 1800

        order_now = read_order(order["id"])
        assert order_now["producer_subtotal_cents"] == 26000
        assert order_now["margin_tier_bp"] == 1800
        assert cheap["hub_margin_cents"] == 3060
        assert dear["hub_margin_cents"] == 1620
        assert order_now["hub_margin_cents"] == 4680
        assert order_now["order_total_cents"] == 30680

        line_now = read_order_line(order["id"], line["id"])
        assert line_now["status"] == "ALLOCATED"
        assert line_now["quantity_allocated"] == 15

    def test_one_line_can_be_filled_from_two_different_producers(self, api):
        """PRD 3.5: "Walking that ranking, the system draws from each item in
        turn while the line still has unfilled units, taking the smaller of the
        units still needed and the item's `quantity_available`. Each draw
        creates an allocation recording its `order_line_id`, its `product_id`,
        the `quantity` drawn, and a snapshot of the item's
        `producer_unit_price_cents`, and the allocation enters `RESERVED`; the
        item's `quantity_committed` rises by the drawn quantity and its
        available pool is re-derived."

        Design: Corner/entities/allocation_junction_links_one_order_line_to_two_products
        """
        _, _, product_one, product_two = self._two_producers_with_priced_supply(
            1800, 1700
        )
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=15)

        validate_success(api.aggregate_order(order["id"], HUB))

        _, line_meta = validate_paginated(
            api.list_allocations(HUB, params={"order_line_id": line["id"]})
        )
        assert line_meta["total_count"] == 2

        product_rows, product_meta = validate_paginated(
            api.list_allocations(HUB, params={"product_id": product_two["id"]})
        )
        assert product_meta["total_count"] == 1
        assert product_rows[0]["quantity"] == 10
        assert product_rows[0]["product_id"] == product_two["id"]
        assert product_rows[0]["order_line_id"] == line["id"]
        assert_allocation(product_rows[0])

    def test_an_item_whose_offer_window_misses_the_delivery_date_is_not_a_candidate(
        self, api
    ):
        """PRD 3.5: "For a given line, a catalog item is a candidate only if
        every one of the following holds: the item is `LISTED`; its
        `commodity_code` equals the line's `commodity_code`; its `storage_class`
        equals the line's `storage_class`; its `unit_of_measure` equals the
        line's `unit_of_measure`; its `quantity_available` is greater than zero;
        the order's `requested_delivery_date` falls at or after the item's
        `offer_window_start` and strictly before its `offer_window_end`; the
        owning producer is `ACTIVE` with compliance currently satisfied; and the
        item passes the buyer's price ceiling."
        PRD 3.5: "Only when **every** line of the order ends at zero allocated
        units does the whole request fail, with `ERR_NO_ELIGIBLE_SUPPLY`, and in
        that case no allocation is persisted and the order remains `DRAFT`."

        Design: Corner/calculations/allocation_excludes_products_whose_offer_window_misses_the_delivery_date
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        product = create_listed_product(
            onboarded["producer_id"],
            quantity_offered=100,
            offer_window_end="2026-09-10T00:00:00Z",
        )
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        add_order_line(order["id"], buyer["id"], quantity_requested=60)

        resp = api.aggregate_order(order["id"], HUB)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SUPPLY.value, 422)

        product_now = read_product(product["id"])
        assert product_now["quantity_committed"] == 0
        assert product_now["quantity_available"] == 100
        assert read_order(order["id"])["fulfillment_status"] == "DRAFT"

    def test_an_item_above_the_buyer_price_ceiling_is_not_a_candidate(self, api):
        """PRD 3.5: "That last clause is worth stating exactly: the item's
        `producer_unit_price_cents`, plus the margin obtained by multiplying
        that price by 1800 basis points, dividing by 10000 and rounding half up
        to a whole cent, must be less than or equal to the line's
        `max_unit_price_cents`."
        PRD 3.5: "Only when **every** line of the order ends at zero allocated
        units does the whole request fail, with `ERR_NO_ELIGIBLE_SUPPLY`, and in
        that case no allocation is persisted and the order remains `DRAFT`."

        Design: Corner/calculations/allocation_excludes_products_above_the_buyer_price_ceiling
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        product = create_listed_product(
            onboarded["producer_id"],
            quantity_offered=100,
            producer_unit_price_cents=2200,
        )
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        add_order_line(
            order["id"], buyer["id"], quantity_requested=60, max_unit_price_cents=2500
        )

        # 2200 + round_half_up(2200 * 1800 / 10000) == 2596, above the 2500 ceiling.
        resp = api.aggregate_order(order["id"], HUB)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SUPPLY.value, 422)
        assert read_product(product["id"])["quantity_committed"] == 0

    def test_running_aggregation_a_second_time_is_refused(self, api):
        """PRD 3.5: "A hub administrator runs it against an order that is still
        `DRAFT` and that carries at least one demand line; an order in any later
        fulfillment state, or one with no lines at all, is refused with
        `ERR_INVALID_ORDER_STATE`."

        Design: Corner/state_machines/running_aggregation_twice_returns_invalid_order_state
        """
        scenario = setup_scenario(stage="aggregated")

        resp = api.aggregate_order(scenario["order_id"], HUB)
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value, 409)

        _, meta = validate_paginated(
            api.list_allocations(HUB, params={"order_line_id": scenario["line_id"]})
        )
        assert meta["total_count"] == 1
        product = read_product(scenario["product_id"])
        assert product["quantity_committed"] == 60
        assert product["quantity_available"] == 40

    def test_aggregation_is_blocked_when_the_provisional_total_breaches_the_credit_limit(
        self, api
    ):
        """PRD 3.5: "Before the run is allowed to stand, the buyer's exposure is
        tested: the buyer's current `outstanding_balance_cents` plus this
        order's provisional `order_total_cents` must not exceed the buyer's
        `credit_limit_cents`. An order that would push the institution past its
        limit is refused with `ERR_CREDIT_LIMIT_EXCEEDED`, and, as with a failed
        supply search, nothing is persisted — no allocation, no committed
        quantity, no state change."

        Design: Corner/validations/aggregation_blocked_when_the_provisional_total_breaches_the_credit_limit
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        product = create_listed_product(onboarded["producer_id"], quantity_offered=100)
        buyer = create_buyer(credit_limit_cents=100000)
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=60)

        resp = api.aggregate_order(order["id"], HUB)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 422)

        order_now = read_order(order["id"])
        assert order_now["fulfillment_status"] == "DRAFT"
        assert order_now["order_total_cents"] == 0
        assert read_product(product["id"])["quantity_committed"] == 0
        _, meta = validate_paginated(
            api.list_allocations(HUB, params={"order_line_id": line["id"]})
        )
        assert meta["total_count"] == 0


class TestSupplierStateDependency:
    def _draft_order_over_a_suspended_supplier(self, api):
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        product = create_listed_product(pid, quantity_offered=100)
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=60)
        validate_success(
            api.review_producer(
                pid, {"decision": "SUSPEND", "note": "recall investigation"}, HUB
            )
        )
        return product, order, line

    def test_aggregation_fails_when_the_only_supplier_has_been_suspended(self, api):
        """PRD 3.5: "For a given line, a catalog item is a candidate only if
        every one of the following holds: the item is `LISTED`; its
        `commodity_code` equals the line's `commodity_code`; its `storage_class`
        equals the line's `storage_class`; its `unit_of_measure` equals the
        line's `unit_of_measure`; its `quantity_available` is greater than zero;
        the order's `requested_delivery_date` falls at or after the item's
        `offer_window_start` and strictly before its `offer_window_end`; the
        owning producer is `ACTIVE` with compliance currently satisfied; and the
        item passes the buyer's price ceiling."
        PRD 3.5: "Only when **every** line of the order ends at zero allocated
        units does the whole request fail, with `ERR_NO_ELIGIBLE_SUPPLY`, and in
        that case no allocation is persisted and the order remains `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/order_aggregation_depends_on_supplier_producer_state
        """
        product, order, _line = self._draft_order_over_a_suspended_supplier(api)

        resp = api.aggregate_order(order["id"], HUB)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SUPPLY.value, 422)

        order_now = read_order(order["id"])
        assert order_now["fulfillment_status"] == "DRAFT"
        assert order_now["order_total_cents"] == 0
        assert read_product(product["id"])["status"] == "DELISTED"

    def test_a_failed_supply_search_persists_no_allocation(self, api):
        """PRD 3.5: "Only when **every** line of the order ends at zero
        allocated units does the whole request fail, with
        `ERR_NO_ELIGIBLE_SUPPLY`, and in that case no allocation is persisted
        and the order remains `DRAFT`."
        PRD 3.5: "A line that got everything it asked for becomes `ALLOCATED`; a
        line that got some but not all becomes `SHORT`; a line that found no
        candidate at all stays `PENDING` with nothing allocated — and,
        crucially, the run continues to the next line rather than failing."

        Design: Difficulty/cross_entity_state_dependency/order_aggregation_depends_on_supplier_producer_state
        """
        _product, order, line = self._draft_order_over_a_suspended_supplier(api)

        resp = api.aggregate_order(order["id"], HUB)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SUPPLY.value, 422)

        line_now = read_order_line(order["id"], line["id"])
        assert line_now["status"] == "PENDING"
        assert line_now["quantity_allocated"] == 0
        _, meta = validate_paginated(
            api.list_allocations(HUB, params={"order_line_id": line["id"]})
        )
        assert meta["total_count"] == 0


class TestMarginRounding:
    def _order_over_two_equal_priced_items(self, api, price, offered, requested):
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        first = create_listed_product(
            pid, quantity_offered=offered, producer_unit_price_cents=price
        )
        second = create_listed_product(
            pid, quantity_offered=offered, producer_unit_price_cents=price
        )
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=requested)
        return first, second, order, line

    def test_the_order_margin_rounds_per_allocation_before_summing(self, api):
        """PRD 2.6: "First, when an order's margin is computed, the rounding
        happens **once per allocation and the rounded results are then
        summed**; computing the subtotal first and rounding a single time at the
        end produces a different number of whole cents and is wrong under this
        specification."
        PRD 3.5: "With the tier chosen, each allocation records it in
        `margin_bp` and computes its own `hub_margin_cents` by multiplying its
        `producer_amount_cents` by the tier rate, dividing by 10000 and rounding
        half up — per allocation, as §2.6 insists, and only then summed into a
        raw margin total."

        Design: Difficulty/combinatorial_formula/hub_margin_rounded_per_allocation_then_summed
        """
        _first, _second, order, _line = self._order_over_two_equal_priced_items(
            api, price=1805, offered=5, requested=8
        )

        data = validate_success(api.aggregate_order(order["id"], HUB))
        assert_buyer_order(data)
        assert data["producer_subtotal_cents"] == 14440
        assert data["margin_tier_bp"] == 1800
        assert data["hub_margin_cents"] == 2600, (
            "rounding per allocation gives 1625 + 975 == 2600"
        )
        assert data["hub_margin_cents"] != 2599, (
            "summing first and rounding once would give 2599"
        )
        assert data["order_total_cents"] == 17040
        assert_order_total_identity(data)

    def test_each_allocation_carries_its_own_rounded_margin(self, api):
        """PRD 3.5: "With the tier chosen, each allocation records it in
        `margin_bp` and computes its own `hub_margin_cents` by multiplying its
        `producer_amount_cents` by the tier rate, dividing by 10000 and rounding
        half up — per allocation, as §2.6 insists, and only then summed into a
        raw margin total."
        PRD 3.5: "Each demand line rolls up its own allocations in parallel:
        `line_producer_cents` is the sum of their producer amounts,
        `line_margin_cents` the sum of their margins, and `line_total_cents` the
        sum of those two."
        PRD 3.5: "Finally, `order_pallets` is computed by dividing each
        allocation's `quantity` by its item's `units_per_pallet`, rounding
        **each** result up to a whole pallet, and summing those whole pallets."

        Design: Difficulty/combinatorial_formula/hub_margin_rounded_per_allocation_then_summed
        """
        first, second, order, line = self._order_over_two_equal_priced_items(
            api, price=1805, offered=5, requested=8
        )

        validate_success(api.aggregate_order(order["id"], HUB))

        alloc_one = allocations_for_product(first["id"])[0]
        alloc_two = allocations_for_product(second["id"])[0]
        assert alloc_one["quantity"] == 5
        assert alloc_one["producer_amount_cents"] == 9025
        assert alloc_one["hub_margin_cents"] == 1625
        assert alloc_one["buyer_amount_cents"] == 10650
        assert alloc_two["quantity"] == 3
        assert alloc_two["producer_amount_cents"] == 5415
        assert alloc_two["hub_margin_cents"] == 975
        assert alloc_two["buyer_amount_cents"] == 6390
        assert_allocation_money_split(alloc_one)
        assert_allocation_money_split(alloc_two)

        line_now = read_order_line(order["id"], line["id"])
        assert line_now["status"] == "ALLOCATED"
        assert line_now["quantity_allocated"] == 8
        assert line_now["line_total_cents"] == 17040
        assert read_order(order["id"])["order_pallets"] == 2


class TestMarginTierSelection:
    def _order_at_a_pre_margin_subtotal_of_49000(self, api):
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        product = create_listed_product(
            onboarded["producer_id"],
            quantity_offered=100,
            producer_unit_price_cents=1000,
        )
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=49)
        return product, order, line

    def test_the_tier_is_read_from_the_pre_margin_subtotal(self, api):
        """PRD 3.5: "Summing those amounts gives the order's
        `producer_subtotal_cents`, and that **pre-margin** figure alone selects
        the margin tier: a subtotal below 50000 cents takes `margin_tier_bp`
        1800; a subtotal from 50000 cents up to but not including 200000 cents
        takes 1500; from 200000 cents up to but not including 500000 cents takes
        1250; and 500000 cents or more takes 1000."

        Design: Difficulty/combinatorial_formula/hub_margin_tier_keyed_on_pre_margin_subtotal
        """
        _product, order, _line = self._order_at_a_pre_margin_subtotal_of_49000(api)

        data = validate_success(api.aggregate_order(order["id"], HUB))
        assert data["producer_subtotal_cents"] == 49000
        assert data["margin_tier_bp"] == 1800
        assert data["hub_margin_cents"] == 8820
        assert data["order_total_cents"] == 57820
        assert_order_total_identity(data)

    def test_the_tier_is_not_reselected_once_the_margin_crosses_a_boundary(self, api):
        """PRD 3.5: "The tier is selected once, from the subtotal before margin,
        and is **never** re-selected from the order total after the margin has
        been added, even when adding the margin pushes the order across a higher
        boundary; there is no fixed-point iteration here."

        Design: Difficulty/combinatorial_formula/hub_margin_tier_keyed_on_pre_margin_subtotal
        """
        _product, order, line = self._order_at_a_pre_margin_subtotal_of_49000(api)

        validate_success(api.aggregate_order(order["id"], HUB))

        order_now = read_order(order["id"])
        assert order_now["order_total_cents"] == 57820, (
            "the total crosses the 50000-cent boundary but the tier is fixed"
        )
        assert order_now["margin_tier_bp"] != 1500
        assert order_now["margin_tier_bp"] == 1800
        assert order_now["order_pallets"] == 2

        allocation = allocations_for_line(line["id"])[0]
        assert allocation["margin_bp"] == 1800
        assert allocation["buyer_amount_cents"] == 57820

    def test_the_order_margin_floor_tops_up_the_largest_allocation(self, api):
        """PRD 3.5: "The order's `hub_margin_cents` is that raw total, except
        that the hub charges a floor of 2500 cents — 25 dollars — on any order
        it aggregates: when the raw total is below the floor, the order's margin
        is the floor instead, and the difference is added to the
        `hub_margin_cents` of one single allocation, namely the one with the
        largest `producer_amount_cents`, with a tie broken in favour of the
        allocation created earliest."

        Design: Corner/calculations/minimum_order_margin_floor_tops_up_the_largest_allocation
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        create_listed_product(
            onboarded["producer_id"],
            quantity_offered=20,
            producer_unit_price_cents=1000,
            units_per_pallet=20,
        )
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        line = add_order_line(order["id"], buyer["id"], quantity_requested=10)

        data = validate_success(api.aggregate_order(order["id"], HUB))
        assert data["producer_subtotal_cents"] == 10000
        assert data["margin_tier_bp"] == 1800
        assert data["hub_margin_cents"] == 2500
        assert data["order_total_cents"] == 12500

        allocation = allocations_for_line(line["id"])[0]
        assert allocation["hub_margin_cents"] == 2500
        assert allocation["buyer_amount_cents"] == 12500
        assert read_order_line(order["id"], line["id"])["line_margin_cents"] == 2500


class TestAllocationRead:
    def test_reading_an_allocation_exposes_the_full_money_split(self, api):
        """PRD 3.5: "Each allocation's `buyer_amount_cents` is then its producer
        amount plus its (possibly topped-up) margin, and the order's
        `order_total_cents` is `producer_subtotal_cents` plus
        `hub_margin_cents`."
        PRD 3.5: "Each new allocation starts with `delivered_quantity`,
        `rejected_quantity`, `producer_charge_cents` and `hub_absorbed_cents` at
        0, no `staged_temp_c` recorded and `temp_excursion` false."

        Design: Corner/endpoints/allocation_read_exposes_the_full_producer_hub_money_split
        """
        scenario = setup_scenario(stage="aggregated")

        data = validate_success(api.get_allocation(scenario["allocation_id"], HUB))
        assert data["producer_amount_cents"] == 108000
        assert data["hub_margin_cents"] == 16200
        assert data["buyer_amount_cents"] == 124200
        assert_allocation_money_split(data)
        assert data["status"] == "RESERVED"
        assert data["margin_bp"] == 1500
        assert data["staged_temp_c"] is None
        assert data["temp_excursion"] is False
