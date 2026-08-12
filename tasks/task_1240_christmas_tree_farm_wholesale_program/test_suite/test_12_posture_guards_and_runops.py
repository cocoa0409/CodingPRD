"""Season posture gates, advance guards, and the ops-run checkpoint."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    FM,
    OWNER,
    advance_season_to,
    bucket_of,
    create_buyer,
    create_draft_order,
    create_season,
    get_success_data,
    list_order_allocations,
    set_clock,
    setup_booking_season,
    submit_order,
    validate_error,
    validate_paginated,
    api_client,
    make_buyer_headers,
)


class TestOrderCreatePostureGate:
    def test_create_in_planning_posture_forbidden(self, api):
        """PRD §3.3: "Orders are born `DRAFT` with `allocated_qty` at zero;
        creation outside `BOOKING` is refused with `ERR_POSTURE_FORBIDS`."
        PRD §2.7: "Wholesale order creation and order submission require
        `BOOKING`; allocation against an order requires `BOOKING` or
        `HARVEST`."

        Design: Corner/validations/order_create_in_planning_posture_forbidden
        """
        season = create_season()  # PLANNING; clock at startup default
        buyer = create_buyer()
        resp = api.create_order(
            {
                "season_id": season["id"],
                "buyer_account_id": buyer["id"],
                "species": "NOBLE_FIR",
                "height_class": "H_6_7",
                "quantity": 5,
                "unit_price_cents": 400,
            },
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POSTURE_FORBIDS)

    def test_posture_rejected_create_persists_nothing(self, api):
        """PRD §3.3: "Orders are born `DRAFT` with `allocated_qty` at zero;
        creation outside `BOOKING` is refused with `ERR_POSTURE_FORBIDS`."
        PRD §3.3: "The order list supports filters on `buyer_account_id`,
        `season_id`, and `status`, and a buyer sees only its own orders."

        Design: Corner/validations/order_create_in_planning_posture_forbidden
        """
        season = create_season()
        buyer = create_buyer()
        api.create_order(
            {
                "season_id": season["id"],
                "buyer_account_id": buyer["id"],
                "species": "NOBLE_FIR",
                "height_class": "H_6_7",
                "quantity": 5,
                "unit_price_cents": 400,
            },
            make_buyer_headers(buyer["id"]),
        )
        data, meta = validate_paginated(
            api.list_orders(FM, params={"buyer_account_id": buyer["id"]})
        )
        assert meta["total_count"] == 0


class TestHarvestAdvanceGuard:
    def _setup_draft_order_booking(self):
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=5, unit_price_cents=400,
        )
        set_clock("2026-11-01T00:00:00Z")  # harvest_window_start as midnight UTC
        ctx["buyer"] = buyer
        ctx["order"] = order
        return ctx

    def test_draft_order_blocks_harvest_advance(self, api):
        """PRD §3.8: "Opening harvest — `BOOKING` → `HARVEST` — requires the
        clock to have reached the season's `harvest_window_start` read as
        midnight UTC, and requires that no order of the season remains in
        `DRAFT` (the run-ops expiry sweep is the mechanism that clears
        stragglers)."
        PRD §3.8: "Each step has its own guard, and a failed guard is rejected
        with `ERR_POSTURE_GUARD_FAILED` (HTTP 409)."

        Design: Corner/validations/advance_to_harvest_with_draft_order_blocked
        """
        ctx = self._setup_draft_order_booking()
        resp = api.advance_posture(ctx["season"]["id"], "HARVEST", OWNER)
        validate_error(resp, ApiErrorId.ERR_POSTURE_GUARD_FAILED)
        season_now = get_success_data(api.get_season(ctx["season"]["id"], OWNER))
        assert season_now["posture"] == "BOOKING"

    def test_cancelling_draft_unblocks_advance(self, api):
        """PRD §3.3: "Cancelling from `DRAFT` is unconditional."
        PRD §3.8: "Opening harvest — `BOOKING` → `HARVEST` — requires the clock
        to have reached the season's `harvest_window_start` read as midnight
        UTC, and requires that no order of the season remains in `DRAFT` (the
        run-ops expiry sweep is the mechanism that clears stragglers)."

        Design: Corner/validations/advance_to_harvest_with_draft_order_blocked
        """
        ctx = self._setup_draft_order_booking()
        resp = api.advance_posture(ctx["season"]["id"], "HARVEST", OWNER)
        validate_error(resp, ApiErrorId.ERR_POSTURE_GUARD_FAILED)
        cancelled = get_success_data(
            api.cancel_order(ctx["order"]["id"],
                             make_buyer_headers(ctx["buyer"]["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        season = get_success_data(
            api.advance_posture(ctx["season"]["id"], "HARVEST", OWNER)
        )
        assert season["posture"] == "HARVEST"


class TestRunOpsBackfill:
    def _setup_submitted_unallocated(self):
        ctx = setup_booking_season(H_6_7=300)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=30, unit_price_cents=400,
        )
        order = submit_order(order["id"], buyer["id"])
        ctx["buyer"] = buyer
        ctx["order"] = order
        return ctx

    def test_runops_creates_backfill_allocation(self, api):
        """PRD §3.8: "Third — only while the posture is `BOOKING` or `HARVEST`
        — the backfill walks every `SUBMITTED` order of the season whose
        `allocated_qty` still falls short of its `quantity`, oldest
        `submitted_at` first with creation time ascending as the tie-break, and
        runs the allocation waterfall for each order's unallocated remainder."
        PRD §3.4: "each contribution creates an **Allocation** in `RESERVED`
        status recording the `order_id`, the `bucket_id`, and the reserved
        `quantity`, with its `cut_qty` and `loaded_qty` starting at zero, and
        adds that quantity to the bucket's `reserved_count`."

        Design: Difficulty/transitive_cascade/runops_backfill_allocation_cascade
        """
        ctx = self._setup_submitted_unallocated()
        season = get_success_data(api.run_ops(ctx["season"]["id"], OWNER))
        assert season["ops_run_index"] == 1
        allocs = list_order_allocations(ctx["order"]["id"])
        assert len(allocs) == 1, "backfill created exactly one allocation"
        assert allocs[0]["quantity"] == 30
        assert allocs[0]["status"] == "RESERVED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["reserved_count"] == 30
        assert bucket["standing_count"] == 300

    def test_backfill_flips_order_to_allocated(self, api):
        """PRD §3.4: "When `allocated_qty` reaches the full `quantity` —
        whether through an explicit allocate call, an ops-run backfill, or a
        recompute after a release — the order moves `SUBMITTED` → `ALLOCATED`."
        PRD §3.8: "Fourth, the season's `ops_run_index` increments by one,
        marking the checkpoint."

        Design: Difficulty/transitive_cascade/runops_backfill_allocation_cascade
        """
        ctx = self._setup_submitted_unallocated()
        get_success_data(api.run_ops(ctx["season"]["id"], OWNER))
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["allocated_qty"] == 30
        assert order_now["status"] == "ALLOCATED"


class TestRunOpsDraftExpiry:
    def _setup_draft_past_close(self):
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=5, unit_price_cents=400,
        )
        set_clock(CLOCK["PAST_BOOKING_CLOSE"])  # 2026-09-01 > booking_close_at
        ctx["buyer"] = buyer
        ctx["order"] = order
        return ctx

    def test_first_run_expires_draft_order(self, api):
        """PRD §3.8: "Second, every wholesale order of the season still in
        `DRAFT` when the clock has passed `booking_close_at` moves to terminal
        `EXPIRED`."
        PRD §3.8: "Fourth, the season's `ops_run_index` increments by one,
        marking the checkpoint."

        Design: Corner/endpoints/run_ops_second_run_sweeps_nothing
        """
        ctx = self._setup_draft_past_close()
        season = get_success_data(api.run_ops(ctx["season"]["id"], OWNER))
        assert season["ops_run_index"] == 1
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["status"] == "EXPIRED"

    def test_second_run_changes_no_state(self, api):
        """PRD §3.8: "Second, every wholesale order of the season still in
        `DRAFT` when the clock has passed `booking_close_at` moves to terminal
        `EXPIRED`."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource, including mutations the
        server applies automatically as side effects of other operations."

        Design: Corner/endpoints/run_ops_second_run_sweeps_nothing
        """
        ctx = self._setup_draft_past_close()
        get_success_data(api.run_ops(ctx["season"]["id"], OWNER))
        after_first = get_success_data(api.get_order(ctx["order"]["id"], FM))
        season = get_success_data(api.run_ops(ctx["season"]["id"], OWNER))
        assert season["ops_run_index"] == 2
        after_second = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert after_second["status"] == "EXPIRED"
        assert after_second["version"] == after_first["version"], (
            "second run mutates nothing, so no version bump"
        )
        assert after_second["updated_at"] == after_first["updated_at"]


class TestSubmitCancelledOrderPriority:
    def _setup_cancelled_order_on_credit_hold(self):
        ctx = setup_booking_season(H_6_7=100)
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=10, unit_price_cents=400,
        )
        submit_order(order["id"], buyer["id"])
        get_success_data(
            api_client.cancel_order(order["id"], make_buyer_headers(buyer["id"]))
        )
        get_success_data(
            api_client.set_buyer_standing(buyer["id"], "CREDIT_HOLD", OWNER)
        )
        return ctx, buyer, order

    def test_state_error_wins_over_credit_hold(self, api):
        """PRD §2.6: "When several checks could reject the same request, the
        system evaluates them in a fixed pipeline order, and the earliest
        failing check determines the error returned."
        PRD §2.6: "sixth, state-machine from-state validity, including
        terminal-state lockdown and the requirement that a posture advance name
        the immediate next posture (`ERR_INVALID_STATE`); seventh, the season
        posture gate (`ERR_POSTURE_FORBIDS`); eighth, the advance-posture guard
        conditions (`ERR_POSTURE_GUARD_FAILED`); ninth, temporal window checks
        (`ERR_OUTSIDE_HARVEST_WINDOW`, `ERR_OUTSIDE_SHIPPING_WINDOW`); tenth,
        referential business rules such as block harvestability, block
        occupancy, u-cut designation, crew activity, buyer standing, and
        ticket-block alignment".

        Design: Difficulty/priority_pair_validation_conflict/submit_cancelled_order_with_credit_hold_state_wins
        """
        _ctx, buyer, order = self._setup_cancelled_order_on_credit_hold()
        resp = api.submit_order(order["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_submit_leaves_order_cancelled(self, api):
        """PRD §3.3: "`CANCELLED` is terminal, as are `CLOSED` and `EXPIRED`."
        PRD §2.6: "When several checks could reject the same request, the
        system evaluates them in a fixed pipeline order, and the earliest
        failing check determines the error returned."

        Design: Difficulty/priority_pair_validation_conflict/submit_cancelled_order_with_credit_hold_state_wins
        """
        _ctx, buyer, order = self._setup_cancelled_order_on_credit_hold()
        api.submit_order(order["id"], make_buyer_headers(buyer["id"]))
        order_now = get_success_data(api.get_order(order["id"], FM))
        assert order_now["status"] == "CANCELLED"
        buyer_now = get_success_data(api.get_buyer_account(buyer["id"], OWNER))
        assert buyer_now["exposure_cents"] == 0, (
            "no duplicate invoice accrues from the rejected submit"
        )
