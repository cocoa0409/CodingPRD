"""Order lifecycle: submit/cancel legality, release cascade, regression loop,
buyer exposure conservation, and list filtering."""
from test_helpers import (
    ApiErrorId,
    FM,
    OWNER,
    allocate_order,
    bucket_of,
    create_buyer,
    create_draft_order,
    get_success_data,
    list_buckets,
    list_order_allocations,
    setup_allocated_order,
    setup_booking_season,
    setup_cut_allocation,
    submit_order,
    validate_error,
    validate_paginated,
    api_client,
    make_buyer_headers,
)


class TestDoubleSubmit:
    def test_second_submit_rejected_invalid_state(self, api):
        """PRD §2.6: "sixth, state-machine from-state validity, including
        terminal-state lockdown and the requirement that a posture advance name
        the immediate next posture (`ERR_INVALID_STATE`)".
        PRD §3.3: "A successful submission stamps `submitted_at` with the
        logical clock, moves the order `DRAFT` → `SUBMITTED`, and adds the
        invoice total to the buyer's exposure."

        Design: Corner/state_machines/order_double_submit_returns_invalid_state
        """
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=10, unit_price_cents=400,
        )
        submit_order(order["id"], buyer["id"])
        resp = api.submit_order(order["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_submit_charges_exposure_once(self, api):
        """PRD §3.3: "A buyer's `exposure_cents` is a computed figure: the sum
        of `invoice_total_cents` over exactly that buyer's orders sitting in
        `SUBMITTED` or `ALLOCATED` — orders in `DRAFT`, `CLOSED`, `CANCELLED`,
        or `EXPIRED` contribute nothing."

        Design: Corner/state_machines/order_double_submit_returns_invalid_state
        """
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=10, unit_price_cents=400,
        )
        submit_order(order["id"], buyer["id"])
        api.submit_order(order["id"], make_buyer_headers(buyer["id"]))
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 4000, "invoice charged once"


class TestTerminalCancelLockdown:
    def test_cancel_of_cancelled_order_rejected(self, api):
        """PRD §3.3: "`CANCELLED` is terminal, as are `CLOSED` and `EXPIRED`."
        PRD §2.6: "sixth, state-machine from-state validity, including
        terminal-state lockdown and the requirement that a posture advance name
        the immediate next posture (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/cancel_terminal_order_returns_invalid_state
        """
        ctx = setup_booking_season(H_6_7=50)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=3, unit_price_cents=400,
        )
        cancelled = get_success_data(
            api.cancel_order(order["id"], make_buyer_headers(buyer["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        # Even a FarmManager cannot cancel a terminal order.
        resp2 = api.cancel_order(order["id"], FM)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
        order_now = get_success_data(api.get_order(order["id"], FM))
        assert order_now["status"] == "CANCELLED"


class TestCancelReleasesAllocations:
    def test_cancel_releases_reserved_allocation(self, api):
        """PRD §3.3: "Cancelling from `SUBMITTED` or `ALLOCATED` requires that
        no allocation of the order stands in `CUT` or `LOADED`, failing with
        `ERR_ORDER_HAS_CUT_ALLOCATIONS` (HTTP 409); on success every `RESERVED`
        allocation of the order is released back to its bucket (each bucket's
        `reserved_count` is restored by the released quantity) and the buyer's
        exposure is relieved of the invoice total."

        Design: Corner/state_machines/order_cancel_releases_reserved_allocations
        """
        ctx = setup_allocated_order(quantity=25, unit_price_cents=400, H_6_7=100)
        allocation = ctx["allocation"]
        assert allocation["status"] == "RESERVED"
        cancelled = get_success_data(api.cancel_order(ctx["order"]["id"], FM))
        assert cancelled["status"] == "CANCELLED"
        alloc_now = get_success_data(api.get_allocation(allocation["id"], FM))
        assert alloc_now["status"] == "RELEASED"

    def test_cancel_restores_bucket_and_exposure(self, api):
        """PRD §3.3: "on success every `RESERVED` allocation of the order is
        released back to its bucket (each bucket's `reserved_count` is restored
        by the released quantity) and the buyer's exposure is relieved of the
        invoice total."
        PRD §3.4: "a `FarmManager` may release an allocation that is still
        `RESERVED`, which returns its full `quantity` to the bucket's
        `reserved_count`, deducts it from the order's `allocated_qty`
        (regressing the order as above), and moves the allocation to
        `RELEASED`."

        Design: Corner/state_machines/order_cancel_releases_reserved_allocations
        """
        ctx = setup_allocated_order(quantity=25, unit_price_cents=400, H_6_7=100)
        get_success_data(api.cancel_order(ctx["order"]["id"], FM))
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["reserved_count"] == 0
        assert bucket["standing_count"] == 100, "release never destroys standing"
        buyer_now = get_success_data(
            api.get_buyer_account(ctx["buyer"]["id"], OWNER)
        )
        assert buyer_now["exposure_cents"] == 0


class TestRegressionLoop:
    def _setup(self):
        ctx = setup_allocated_order(quantity=100, unit_price_cents=400, H_6_7=300)
        return ctx

    def test_full_allocation_then_release_regresses_order(self, api):
        """PRD §3.4: "When `allocated_qty` reaches the full `quantity` —
        whether through an explicit allocate call, an ops-run backfill, or a
        recompute after a release — the order moves `SUBMITTED` → `ALLOCATED`."
        PRD §3.4: "Conversely, whenever a release or an over-reservation sweep
        leaves `allocated_qty` below `quantity`, an `ALLOCATED` order regresses
        to `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/order_submitted_allocated_regression_loop
        """
        ctx = self._setup()
        assert ctx["allocate_result"]["order_status"] == "ALLOCATED"
        get_success_data(api.release_allocation(ctx["allocation"]["id"], FM))
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["status"] == "SUBMITTED", "release regresses the order"
        assert order_now["allocated_qty"] == 0

    def test_reallocation_after_regression_closes_loop(self, api):
        """PRD §3.4: "Conversely, whenever a release or an over-reservation
        sweep leaves `allocated_qty` below `quantity`, an `ALLOCATED` order
        regresses to `SUBMITTED`. This `SUBMITTED` ↔ `ALLOCATED` loop can cycle
        any number of times."

        Design: Difficulty/non_linear_state_machine/order_submitted_allocated_regression_loop
        """
        ctx = self._setup()
        get_success_data(api.release_allocation(ctx["allocation"]["id"], FM))
        mid = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert mid["status"] == "SUBMITTED"
        result = allocate_order(mid["id"], 100, mid["version"])
        assert result["order_status"] == "ALLOCATED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["reserved_count"] == 100, "re-reserved after the loop"


class TestExposureConservation:
    def _setup_two_submitted(self):
        ctx = setup_booking_season(H_6_7=100, H_7_8=700)
        buyer = create_buyer()
        o1 = create_draft_order(
            ctx["season"]["id"], buyer["id"], species="NOBLE_FIR",
            height_class="H_6_7", quantity=100, unit_price_cents=500,
        )
        o1 = submit_order(o1["id"], buyer["id"])
        o2 = create_draft_order(
            ctx["season"]["id"], buyer["id"], species="GRAND_FIR",
            height_class="H_7_8", quantity=600, unit_price_cents=500,
        )
        o2 = submit_order(o2["id"], buyer["id"])
        return ctx, buyer, o1, o2

    def test_submitted_orders_accumulate_exposure(self, api):
        """PRD §3.3: "A buyer's `exposure_cents` is a computed figure: the sum
        of `invoice_total_cents` over exactly that buyer's orders sitting in
        `SUBMITTED` or `ALLOCATED` — orders in `DRAFT`, `CLOSED`, `CANCELLED`,
        or `EXPIRED` contribute nothing."

        Design: Difficulty/compensating_invariant/order_submit_cancel_buyer_exposure_conservation
        """
        _ctx, buyer, o1, o2 = self._setup_two_submitted()
        # o1: 100*500 = 50000 - round_half_up(50000*0.03)=1500 -> 48500
        assert o1["invoice_total_cents"] == 48500
        # o2: 600*500 = 300000 - round_half_up(300000*0.08)=24000 -> 276000
        assert o2["invoice_total_cents"] == 276000
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 324500

    def test_cancel_removes_exactly_its_invoice(self, api):
        """PRD §3.3: "on success every `RESERVED` allocation of the order is
        released back to its bucket (each bucket's `reserved_count` is restored
        by the released quantity) and the buyer's exposure is relieved of the
        invoice total."

        Design: Difficulty/compensating_invariant/order_submit_cancel_buyer_exposure_conservation
        """
        _ctx, buyer, o1, o2 = self._setup_two_submitted()
        cancelled = get_success_data(
            api.cancel_order(o1["id"], make_buyer_headers(buyer["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 276000, (
            "exactly order2's invoice remains — no drift from the pair"
        )


class TestCancelWithCutAllocations:
    def test_cancel_rejected_once_trees_cut(self, api):
        """PRD §3.3: "Cancelling from `SUBMITTED` or `ALLOCATED` requires that
        no allocation of the order stands in `CUT` or `LOADED`, failing with
        `ERR_ORDER_HAS_CUT_ALLOCATIONS` (HTTP 409); on success every `RESERVED`
        allocation of the order is released back to its bucket (each bucket's
        `reserved_count` is restored by the released quantity) and the buyer's
        exposure is relieved of the invoice total."

        Design: Corner/validations/order_cancel_with_cut_allocation_rejected
        """
        ctx = setup_cut_allocation(quantity=10, unit_price_cents=400, H_6_7=50,
                                   crew_size=3)
        resp = api.cancel_order(
            ctx["order"]["id"], make_buyer_headers(ctx["buyer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_CUT_ALLOCATIONS)

    def test_rejected_cancel_leaves_order_and_exposure(self, api):
        """PRD §3.3: "Cancelling from `SUBMITTED` or `ALLOCATED` requires that
        no allocation of the order stands in `CUT` or `LOADED`, failing with
        `ERR_ORDER_HAS_CUT_ALLOCATIONS` (HTTP 409); on success every `RESERVED`
        allocation of the order is released back to its bucket (each bucket's
        `reserved_count` is restored by the released quantity) and the buyer's
        exposure is relieved of the invoice total."
        PRD §3.3: "A buyer's `exposure_cents` is a computed figure: the sum of
        `invoice_total_cents` over exactly that buyer's orders sitting in
        `SUBMITTED` or `ALLOCATED` — orders in `DRAFT`, `CLOSED`, `CANCELLED`,
        or `EXPIRED` contribute nothing."

        Design: Corner/validations/order_cancel_with_cut_allocation_rejected
        """
        ctx = setup_cut_allocation(quantity=10, unit_price_cents=400, H_6_7=50,
                                   crew_size=3)
        api.cancel_order(
            ctx["order"]["id"], make_buyer_headers(ctx["buyer"]["id"])
        )
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["status"] == "ALLOCATED"
        buyer_now = get_success_data(
            api.get_buyer_account(ctx["buyer"]["id"], OWNER)
        )
        assert buyer_now["exposure_cents"] == 4000


class TestOrderListFiltering:
    def test_buyer_account_id_filter_isolates_orders(self, api):
        """PRD §3.3: "The order list supports filters on `buyer_account_id`,
        `season_id`, and `status`, and a buyer sees only its own orders."

        Design: Corner/endpoints/order_list_filter_by_buyer
        """
        ctx = setup_booking_season(H_6_7=100, H_7_8=100)
        buyer_a = create_buyer(name="Buyer A")
        buyer_b = create_buyer(name="Buyer B")
        order_a = create_draft_order(
            ctx["season"]["id"], buyer_a["id"], species="NOBLE_FIR",
            height_class="H_6_7", quantity=5, unit_price_cents=400,
        )
        create_draft_order(
            ctx["season"]["id"], buyer_b["id"], species="GRAND_FIR",
            height_class="H_7_8", quantity=7, unit_price_cents=600,
        )
        data, meta = validate_paginated(
            api.list_orders(FM, params={"buyer_account_id": buyer_a["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == order_a["id"]

    def test_buyer_role_sees_only_own_orders(self, api):
        """PRD §2.1: "a wholesale buyer may create orders only under its own
        account, may read only its own account and its own orders, may cancel
        only its own orders, and sees only allocations belonging to its own
        orders. Any mismatch is rejected with `ERR_FORBIDDEN`."
        PRD §3.3: "The order list supports filters on `buyer_account_id`,
        `season_id`, and `status`, and a buyer sees only its own orders."

        Design: Corner/endpoints/order_list_filter_by_buyer
        """
        ctx = setup_booking_season(H_6_7=100, H_7_8=100)
        buyer_a = create_buyer(name="Buyer A")
        buyer_b = create_buyer(name="Buyer B")
        order_a = create_draft_order(
            ctx["season"]["id"], buyer_a["id"], quantity=5, unit_price_cents=400,
        )
        create_draft_order(
            ctx["season"]["id"], buyer_b["id"], quantity=7, unit_price_cents=600,
        )
        data, meta = validate_paginated(
            api.list_orders(make_buyer_headers(buyer_a["id"]))
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == order_a["id"], "Buyer B's order invisible"


class TestBuyerReadOwnership:
    def _setup_two_buyers_one_order(self):
        ctx = setup_booking_season(H_6_7=100)
        buyer_a = create_buyer(name="Buyer A")
        buyer_b = create_buyer(name="Buyer B")
        order_a = create_draft_order(
            ctx["season"]["id"], buyer_a["id"], quantity=5, unit_price_cents=400,
        )
        return ctx, buyer_a, buyer_b, order_a

    def test_buyer_reading_other_buyers_order_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `WholesaleBuyer`, `X-User-ID` is the
        `id` of the acting `BuyerAccount`. Ownership checks on any resource
        that references a buyer compare the resource's `buyer_account_id` field
        to `X-User-ID`: a wholesale buyer may create orders only under its own
        account, may read only its own account and its own orders, may cancel
        only its own orders, and sees only allocations belonging to its own
        orders. Any mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/buyer_cannot_read_other_buyers_order
        """
        _ctx, buyer_a, buyer_b, order_a = self._setup_two_buyers_one_order()
        resp = api.get_order(order_a["id"], make_buyer_headers(buyer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_buyer_reading_own_order_allowed(self, api):
        """PRD §2.1: "a wholesale buyer may create orders only under its own
        account, may read only its own account and its own orders, may cancel
        only its own orders, and sees only allocations belonging to its own
        orders. Any mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/buyer_cannot_read_other_buyers_order
        """
        _ctx, buyer_a, _buyer_b, order_a = self._setup_two_buyers_one_order()
        data = get_success_data(
            api.get_order(order_a["id"], make_buyer_headers(buyer_a["id"]))
        )
        assert data["id"] == order_a["id"]
        assert data["buyer_account_id"] == buyer_a["id"]


class TestSharedCancelOperation:
    def test_farm_manager_cancels_buyers_submitted_order(self, api):
        """PRD §3.3: "A buyer may cancel its own order, and a `FarmManager` may
        cancel any order."

        Design: Corner/rbac/farm_manager_cancels_buyer_order_shared_op
        """
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=10, unit_price_cents=400,
        )
        submit_order(order["id"], buyer["id"])
        cancelled = get_success_data(api.cancel_order(order["id"], FM))
        assert cancelled["status"] == "CANCELLED"

    def test_shared_cancel_relieves_exposure(self, api):
        """PRD §3.3: "on success every `RESERVED` allocation of the order is
        released back to its bucket (each bucket's `reserved_count` is restored
        by the released quantity) and the buyer's exposure is relieved of the
        invoice total."

        Design: Corner/rbac/farm_manager_cancels_buyer_order_shared_op
        """
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=10, unit_price_cents=400,
        )
        submit_order(order["id"], buyer["id"])
        get_success_data(api.cancel_order(order["id"], FM))
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 0
