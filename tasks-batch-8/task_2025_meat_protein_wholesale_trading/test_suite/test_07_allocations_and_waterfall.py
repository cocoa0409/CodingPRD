"""The weekly allocation waterfall: sheet-state gates, tier ordering, partial
grants and shortfalls, forward earmarking, rerun idempotency, and the
confirm/cancel conservation of line pounds and customer exposure."""
from test_helpers import (
    WEEK_1,
    ApiErrorId,
    add_sheet_line,
    api_client,
    assert_allocation,
    create_allocation_payload,
    create_customer,
    create_forward_contract,
    create_product,
    create_sheet,
    get_allocation,
    get_contract,
    get_customer,
    get_line,
    get_lot,
    load_out_shipment,
    make_customer_rep_headers,
    publish_sheet,
    request_allocation,
    run_sheet,
    setup_confirmed_allocation,
    validate_error,
    validate_success,
)


class TestAllocationSheetStateGate:
    def test_allocation_blocked_when_sheet_not_published(self):
        """PRD §3.6: "The line must sit on a `PUBLISHED` sheet, else
        `ERR_PRICE_SHEET_NOT_PUBLISHED`"

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_when_sheet_not_published
        """
        product = create_product(product_code="RIBEYE-I", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-I")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)

        blocked = api_client.create_allocation(
            create_allocation_payload(customer["id"], line["id"], 100),
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_PRICE_SHEET_NOT_PUBLISHED)

        publish_sheet(sheet["id"])
        ok = api_client.create_allocation(
            create_allocation_payload(customer["id"], line["id"], 100),
            make_customer_rep_headers(customer["id"]),
        )
        data = validate_success(ok, expected_status=201)
        assert_allocation(data)
        assert data["status"] == "REQUESTED"

    def test_allocation_blocked_when_sheet_closed(self, desk_admin_headers):
        """PRD §3.6: "The line must sit on a `PUBLISHED` sheet, else
        `ERR_PRICE_SHEET_NOT_PUBLISHED`"
        PRD §3.2: "Closing a `PUBLISHED` sheet — the only state from which a
        close produces `CLOSED`; a sheet in any other non-`DRAFT` state has
        already left the market — moves it to `CLOSED`"

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_when_sheet_not_published
        """
        product = create_product(product_code="RIBEYE-I2", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-I2")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])
        closed = api_client.close_price_sheet(sheet["id"], desk_admin_headers)
        assert validate_success(closed)["status"] == "CLOSED"

        resp = api_client.create_allocation(
            create_allocation_payload(customer["id"], line["id"], 100),
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_SHEET_NOT_PUBLISHED)


class TestConfirmCancelConservation:
    def test_confirm_moves_line_lbs_and_exposure(self):
        """PRD §3.6: "A grant greater than zero confirms the allocation: it
        moves from `REQUESTED` to `CONFIRMED`, its `allocated_lbs` is set to
        the grant — a partial grant confirms below the requested quantity —
        its `unit_price_cents` is set to the applicable price, and the granted
        weight is added to the line's `allocated_lbs`"
        PRD §2.10: "Its value is an aggregation: sum, over the customer's
        allocations in `CONFIRMED` or `SHIPPED` status, each allocation's
        `allocated_lbs` multiplied by its `unit_price_cents`; then subtract
        the `final_settlement_cents` of the customer's claims in `SETTLED_PAID`
        status."

        Design: Difficulty/compensating_invariant/allocation_confirm_cancel_exposure_conservation
        """
        product = create_product(product_code="RIBEYE-L", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-L")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])
        alloc = request_allocation(customer, line["id"], 300)

        run_sheet(sheet["id"])

        alloc_after = get_allocation(alloc["id"])
        assert alloc_after["status"] == "CONFIRMED"
        assert alloc_after["allocated_lbs"] == 300
        assert alloc_after["unit_price_cents"] == 700
        assert get_line(line["id"])["allocated_lbs"] == 300
        customer_after = get_customer(customer["id"])
        assert customer_after["outstanding_exposure_cents"] == 210_000
        assert customer_after["status"] == "ACTIVE"

    def test_cancel_returns_line_lbs_and_exposure_to_zero(self):
        """PRD §3.6: "Cancelling a confirmed allocation releases its supply:
        the line's `allocated_lbs` — or, for an earmarked allocation, the
        contract's `earmarked_lbs` — is decremented by the allocation's
        `allocated_lbs`, and the customer's exposure is recomputed with
        credit-hold release re-evaluated."
        PRD §3.6: "A `CustomerRep` may cancel a still-`REQUESTED` allocation —
        otherwise `ERR_ALLOCATION_NOT_REQUESTED` — which releases nothing and
        simply closes the request with `cancel_reason` `MANUAL`"

        Design: Difficulty/compensating_invariant/allocation_confirm_cancel_exposure_conservation
        """
        product = create_product(product_code="RIBEYE-L2", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-L2")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])
        alloc = request_allocation(customer, line["id"], 300)
        run_sheet(sheet["id"])

        resp = api_client.cancel_allocation(
            alloc["id"], make_customer_rep_headers(customer["id"]))
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "MANUAL"

        assert get_line(line["id"])["allocated_lbs"] == 0, \
            "the cancel must release the confirmed pounds exactly"
        customer_after = get_customer(customer["id"])
        assert customer_after["outstanding_exposure_cents"] == 0
        assert customer_after["status"] == "ACTIVE"


class TestWaterfallTierOrdering:
    def test_tier_waterfall_partial_and_shortfall(self):
        """PRD §3.6: "Within a line, requests are considered in tier order —
        `TIER_1` before `TIER_2` before `TIER_3` — and, within a tier, in
        request creation order, earliest first."
        PRD §3.6: "A grant of exactly zero — supply exhausted or the credit
        gate's aftermath — moves the allocation from `REQUESTED` to
        `SHORTFALL`."

        Design: Corner/calculations/run_allocation_tier_waterfall_partial_and_shortfall
        """
        product = create_product(product_code="RIBEYE-WF", max_fat_pct=12.0)
        t1 = create_customer(customer_code="CUST-T1", allocation_tier="TIER_1")
        t2 = create_customer(customer_code="CUST-T2", allocation_tier="TIER_2")
        t3 = create_customer(customer_code="CUST-T3", allocation_tier="TIER_3")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 400, 3_000)
        publish_sheet(sheet["id"])

        # Deliberately create the lowest tier first: tier must beat recency.
        a3 = request_allocation(t3, line["id"], 500)
        a2 = request_allocation(t2, line["id"], 1500)
        a1 = request_allocation(t1, line["id"], 2000)

        run_sheet(sheet["id"])

        a1_after = get_allocation(a1["id"])
        assert a1_after["status"] == "CONFIRMED"
        assert a1_after["allocated_lbs"] == 2000
        a2_after = get_allocation(a2["id"])
        assert a2_after["status"] == "CONFIRMED", \
            "a partial grant still confirms"
        assert a2_after["allocated_lbs"] == 1000
        a3_after = get_allocation(a3["id"])
        assert a3_after["status"] == "SHORTFALL"
        assert a3_after["allocated_lbs"] == 0
        assert get_line(line["id"])["allocated_lbs"] == 3000, \
            "the weekly cap is fully consumed"


class TestForwardEarmarkedAllocation:
    def test_earmarked_allocation_prices_from_contract(self):
        """PRD §3.6: "When the allocation under consideration carries a
        `forward_contract_id`, the engine prices and supplies it from the
        contract: the contract must be `OPEN`; the available pool is the
        contract's `committed_lbs` minus its `delivered_lbs` minus its
        `earmarked_lbs`; the applicable price is the contract's
        `fixed_price_per_lb_cents`; and the sheet's remaining supply is not
        consumed by the grant."

        Design: Corner/calculations/forward_earmarked_allocation_pricing
        """
        product = create_product(product_code="RIBEYE-FE", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-FE")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 5_000)
        publish_sheet(sheet["id"])
        contract = create_forward_contract(customer, product["id"],
                                           committed_lbs=1000,
                                           fixed_price_per_lb_cents=650,
                                           delivery_week_start=WEEK_1)
        alloc = request_allocation(customer, line["id"], 400,
                                   forward_contract_id=contract["id"])

        run_sheet(sheet["id"])

        alloc_after = get_allocation(alloc["id"])
        assert alloc_after["status"] == "CONFIRMED"
        assert alloc_after["allocated_lbs"] == 400
        assert alloc_after["unit_price_cents"] == 650, \
            "an earmarked grant prices at the contract, not the sheet line"
        assert get_contract(contract["id"])["earmarked_lbs"] == 400
        assert get_line(line["id"])["allocated_lbs"] == 0, \
            "an earmarked grant does not consume sheet supply"
        assert get_customer(customer["id"])["outstanding_exposure_cents"] == 260_000


class TestRunAllocationRerun:
    def test_run_allocation_rerun_idempotent(self):
        """PRD §3.6: "The engine walks the sheet's lines in the order the lines
        were created, earliest first, considering only the sheet's own
        `REQUESTED` allocations."
        PRD §3.6: "The run returns a summary carrying `confirmed_count`,
        `shortfall_count`, and the full `allocations` collection as processed."

        Design: Corner/cross_cutting/run_allocation_rerun_idempotent
        """
        product = create_product(product_code="RIBEYE-RR2", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-RR2")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])
        alloc = request_allocation(customer, line["id"], 100)

        run1 = run_sheet(sheet["id"])
        assert run1["confirmed_count"] == 1

        run2 = run_sheet(sheet["id"])
        assert run2["confirmed_count"] == 0, \
            "a rerun finds no REQUESTED allocations and confirms nothing"
        assert run2["shortfall_count"] == 0

        alloc_after = get_allocation(alloc["id"])
        assert alloc_after["status"] == "CONFIRMED"
        assert alloc_after["allocated_lbs"] == 100
        assert get_line(line["id"])["allocated_lbs"] == 100, \
            "a rerun must not double-grant"


class TestAllocationCancelGuards:
    def test_allocation_cancel_twice_returns_409(self):
        """PRD §3.6: "A `CustomerRep` may cancel a still-`REQUESTED` allocation
        — otherwise `ERR_ALLOCATION_NOT_REQUESTED`"

        Design: Corner/validations/allocation_cancel_twice_returns_409
        """
        product = create_product(product_code="RIBEYE-CT", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-CT")
        sheet = create_sheet(WEEK_1)
        line = add_sheet_line(sheet["id"], product["id"], 700, 10_000)
        publish_sheet(sheet["id"])
        alloc = request_allocation(customer, line["id"], 50)
        rep = make_customer_rep_headers(customer["id"])

        first = api_client.cancel_allocation(alloc["id"], rep)
        assert validate_success(first)["status"] == "CANCELLED"

        second = api_client.cancel_allocation(alloc["id"], rep)
        validate_error(second, ApiErrorId.ERR_ALLOCATION_NOT_REQUESTED)
        assert get_allocation(alloc["id"])["status"] == "CANCELLED"

    def test_allocation_cancel_blocked_by_open_shipment(self):
        """PRD §3.6: "A `CustomerRep` may also cancel a `CONFIRMED` allocation,
        but only when it has no shipment in `STAGING` or `IN_TRANSIT`;
        otherwise the request fails with `ERR_ALLOCATION_NOT_CANCELLABLE`."

        Design: Corner/validations/allocation_cancel_blocked_by_open_shipment
        """
        ctx = setup_confirmed_allocation(requested_lbs=100, lot_weight=500)
        load_out_shipment(ctx["allocation"]["id"], 100)  # -> STAGING

        resp = api_client.cancel_allocation(
            ctx["allocation"]["id"],
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_CANCELLABLE)
        assert get_allocation(ctx["allocation"]["id"])["status"] == "CONFIRMED"
        assert get_lot(ctx["lot"]["id"])["current_weight_lbs"] == 400
