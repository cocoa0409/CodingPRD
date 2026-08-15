"""Allocation waterfall: eligibility, ranking, boundaries, OCC, consistency."""
from test_helpers import (
    ApiErrorId,
    FM,
    OWNER,
    allocate_order,
    bucket_of,
    create_block,
    create_buyer,
    create_crop_lot,
    create_draft_order,
    create_season,
    get_success_data,
    list_buckets,
    list_order_allocations,
    set_clock,
    setup_booking_season,
    setup_submitted_order,
    submit_order,
    validate_error,
    validate_paginated,
    api_client,
    make_buyer_headers,
    CLOCK,
    advance_season_to,
)


class TestEligiblePoolFiltering:
    def test_species_mismatch_yields_no_eligible_inventory(self, api):
        """PRD §3.4: "The eligible pool is every stand bucket whose lot's
        `species` matches the order's `species`, whose `height_class` matches
        the order's `height_class`, whose lot is `ACTIVE`, and whose
        `available_count` is at least one."
        PRD §3.4: "If the eligible pool is empty or every eligible bucket has
        zero availability — so not a single tree could be reserved — the
        request fails outright with `ERR_NO_ELIGIBLE_INVENTORY` (HTTP 422);
        there is no deferred queue."

        Design: Corner/endpoints/allocate_no_eligible_species_pool
        """
        season = create_season()
        block = create_block(season["id"])
        create_crop_lot(block["id"], species="DOUGLAS_FIR", H_6_7=100)
        set_clock(CLOCK["BOOKING_OPEN"])
        advance_season_to(season["id"], "BOOKING")
        buyer = create_buyer()
        order = create_draft_order(
            season["id"], buyer["id"], species="NOBLE_FIR", height_class="H_6_7",
            quantity=5, unit_price_cents=400,
        )
        order = submit_order(order["id"], buyer["id"])
        resp = api.allocate_order(order["id"], 5, order["version"], FM)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_INVENTORY)

    def test_failed_allocate_creates_no_allocations(self, api):
        """PRD §3.4: "If the eligible pool is empty or every eligible bucket
        has zero availability — so not a single tree could be reserved — the
        request fails outright with `ERR_NO_ELIGIBLE_INVENTORY` (HTTP 422);
        there is no deferred queue."

        Design: Corner/endpoints/allocate_no_eligible_species_pool
        """
        season = create_season()
        block = create_block(season["id"])
        create_crop_lot(block["id"], species="DOUGLAS_FIR", H_6_7=100)
        set_clock(CLOCK["BOOKING_OPEN"])
        advance_season_to(season["id"], "BOOKING")
        buyer = create_buyer()
        order = create_draft_order(
            season["id"], buyer["id"], species="NOBLE_FIR", height_class="H_6_7",
            quantity=5, unit_price_cents=400,
        )
        order = submit_order(order["id"], buyer["id"])
        api.allocate_order(order["id"], 5, order["version"], FM)
        allocs = list_order_allocations(order["id"])
        assert allocs == [], "rejected waterfall creates nothing"
        order_now = get_success_data(api.get_order(order["id"], FM))
        assert order_now["status"] == "SUBMITTED"
        assert order_now["allocated_qty"] == 0


class TestWaterfallRanking:
    def test_oldest_cohort_drained_first(self, api):
        """PRD §3.4: "Eligible buckets are ranked oldest cohort first —
        ascending `planted_year`, then ascending lot creation time, then
        ascending bucket creation time as the final tie-break."
        PRD §3.4: "Walking the ranked pool, each bucket contributes the smaller
        of the remaining need and its own availability; each contribution
        creates an **Allocation** in `RESERVED` status recording the
        `order_id`, the `bucket_id`, and the reserved `quantity`, with its
        `cut_qty` and `loaded_qty` starting at zero, and adds that quantity to
        the bucket's `reserved_count`."

        Design: Corner/calculations/waterfall_splits_across_lots_oldest_first
        """
        season = create_season()
        blk1 = create_block(season["id"], block_code="B-1", acreage=5.0)
        lot1 = create_crop_lot(blk1["id"], planted_year=2018, H_6_7=40)
        blk2 = create_block(season["id"], block_code="B-2", acreage=6.0)
        lot2 = create_crop_lot(blk2["id"], planted_year=2020, H_6_7=60)
        b1 = bucket_of(lot1["id"], "H_6_7")
        b2 = bucket_of(lot2["id"], "H_6_7")
        set_clock(CLOCK["BOOKING_OPEN"])
        advance_season_to(season["id"], "BOOKING")
        buyer = create_buyer()
        order = create_draft_order(
            season["id"], buyer["id"], quantity=70, unit_price_cents=400,
        )
        order = submit_order(order["id"], buyer["id"])
        result = allocate_order(order["id"], 70, order["version"])
        assert result["allocated_now"] == 70
        assert result["order_status"] == "ALLOCATED"
        allocs = list_order_allocations(order["id"])
        assert len(allocs) == 2
        assert allocs[0]["bucket_id"] == b1["id"], "oldest cohort first"
        assert allocs[0]["quantity"] == 40
        assert allocs[1]["bucket_id"] == b2["id"]
        assert allocs[1]["quantity"] == 30

    def test_waterfall_updates_reserved_counts(self, api):
        """PRD §3.4: "each contribution creates an **Allocation** in `RESERVED`
        status recording the `order_id`, the `bucket_id`, and the reserved
        `quantity`, with its `cut_qty` and `loaded_qty` starting at zero, and
        adds that quantity to the bucket's `reserved_count`."
        PRD §2.8: "A bucket's `available_count` is always its `standing_count`
        minus its `reserved_count`; allocation, consignment delivery, tag
        sales, and culls all draw against this figure."

        Design: Corner/calculations/waterfall_splits_across_lots_oldest_first
        """
        season = create_season()
        blk1 = create_block(season["id"], block_code="B-1", acreage=5.0)
        lot1 = create_crop_lot(blk1["id"], planted_year=2018, H_6_7=40)
        blk2 = create_block(season["id"], block_code="B-2", acreage=6.0)
        lot2 = create_crop_lot(blk2["id"], planted_year=2020, H_6_7=60)
        set_clock(CLOCK["BOOKING_OPEN"])
        advance_season_to(season["id"], "BOOKING")
        buyer = create_buyer()
        order = create_draft_order(
            season["id"], buyer["id"], quantity=70, unit_price_cents=400,
        )
        order = submit_order(order["id"], buyer["id"])
        allocate_order(order["id"], 70, order["version"])
        b1_now = bucket_of(lot1["id"], "H_6_7")
        b2_now = bucket_of(lot2["id"], "H_6_7")
        assert b1_now["reserved_count"] == 40
        assert b1_now["available_count"] == 0, "oldest lot fully drained"
        assert b2_now["reserved_count"] == 30
        assert b2_now["available_count"] == 30


class TestAllocateBoundary:
    def _setup(self):
        return setup_submitted_order(quantity=71, unit_price_cents=400, H_6_7=70)

    def test_allocate_exactly_available_drains_pool(self, api):
        """PRD §3.4: "Walking the ranked pool, each bucket contributes the
        smaller of the remaining need and its own availability; each
        contribution creates an **Allocation** in `RESERVED` status recording
        the `order_id`, the `bucket_id`, and the reserved `quantity`, with its
        `cut_qty` and `loaded_qty` starting at zero, and adds that quantity to
        the bucket's `reserved_count`."

        Design: Difficulty/boundary_precision_check/allocate_exactly_available_then_zero_pool
        """
        ctx = self._setup()
        result = allocate_order(ctx["order"]["id"], 70, ctx["order"]["version"])
        assert result["allocated_now"] == 70, "exactly the available 70 accepted"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["available_count"] == 0, "pool drained to the boundary"
        assert bucket["reserved_count"] == 70

    def test_zero_pool_rejects_next_allocate(self, api):
        """PRD §3.4: "If the eligible pool is empty or every eligible bucket
        has zero availability — so not a single tree could be reserved — the
        request fails outright with `ERR_NO_ELIGIBLE_INVENTORY` (HTTP 422);
        there is no deferred queue."

        Design: Difficulty/boundary_precision_check/allocate_exactly_available_then_zero_pool
        """
        ctx = self._setup()
        result = allocate_order(ctx["order"]["id"], 70, ctx["order"]["version"])
        resp = api.allocate_order(
            ctx["order"]["id"], 1, result["order_version"], FM
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_INVENTORY)
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["status"] == "SUBMITTED", "70 < 71, never full"


class TestAllocateOptimisticConcurrency:
    def test_first_allocate_advances_order_version(self, api):
        """PRD §3.4: "This is the API's second optimistic-concurrency point:
        the request must carry `expected_order_version` equal to the order's
        current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412), because a prior allocation or an ops-run backfill may
        already have advanced the order since the client last read it."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource, including mutations the
        server applies automatically as side effects of other operations."

        Design: Corner/complexity_layers/allocate_stale_order_version_occ
        """
        ctx = setup_submitted_order(quantity=10, unit_price_cents=400, H_6_7=50)
        assert ctx["order"]["version"] == 2  # create (1) then submit (2)
        result = allocate_order(ctx["order"]["id"], 4, ctx["order"]["version"])
        assert result["allocated_now"] == 4
        assert result["order_version"] == 3, "allocate mutated the order once"

    def test_stale_order_version_rejected_412(self, api):
        """PRD §2.10: "Allocating against a wholesale order requires the
        request to carry `expected_order_version` equal to the order's current
        `version`; because a prior allocation or an ops-run backfill may
        legitimately have advanced `allocated_qty`, a second writer with a
        stale order version must lose with 412 rather than over-reserving
        against an outdated view of the order."

        Design: Corner/complexity_layers/allocate_stale_order_version_occ
        """
        ctx = setup_submitted_order(quantity=10, unit_price_cents=400, H_6_7=50)
        stale_version = ctx["order"]["version"]
        allocate_order(ctx["order"]["id"], 4, stale_version)
        resp = api.allocate_order(ctx["order"]["id"], 4, stale_version, FM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["allocated_qty"] == 4, "stale write reserved nothing"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["reserved_count"] == 4


class TestAllocateRoleGate:
    def test_buyer_cannot_allocate_own_order(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role, and
        an attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/api/wholesale-orders/{id}/allocate` | Allocate
        inventory to an order via the waterfall (OCC on the order) |
        FarmManager |"

        Design: Corner/rbac/buyer_cannot_allocate_orders
        """
        ctx = setup_submitted_order(quantity=5, unit_price_cents=400, H_6_7=50)
        resp = api.allocate_order(
            ctx["order"]["id"], 5, ctx["order"]["version"],
            make_buyer_headers(ctx["buyer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_forbidden_allocate_creates_nothing(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role, and
        an attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/buyer_cannot_allocate_orders
        """
        ctx = setup_submitted_order(quantity=5, unit_price_cents=400, H_6_7=50)
        api.allocate_order(
            ctx["order"]["id"], 5, ctx["order"]["version"],
            make_buyer_headers(ctx["buyer"]["id"]),
        )
        allocs = list_order_allocations(ctx["order"]["id"])
        assert allocs == []
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["status"] == "SUBMITTED"


class TestImmediateConsistency:
    def test_allocate_response_reports_totals(self, api):
        """PRD §3.4: "The response reports the `order_id`, the trees reserved
        by this call (`allocated_now`), the order's cumulative
        `allocated_total`, the created `allocation_ids`, and the resulting
        `order_status` and `order_version`."

        Design: Corner/consistency_model/immediate_consistency_after_allocate
        """
        ctx = setup_submitted_order(quantity=12, unit_price_cents=400, H_6_7=50)
        result = allocate_order(ctx["order"]["id"], 12, ctx["order"]["version"])
        assert result["allocated_now"] == 12
        assert result["allocated_total"] == 12
        assert result["order_status"] == "ALLOCATED"
        assert len(result["allocation_ids"]) == 1

    def test_order_and_bucket_reads_reflect_allocation_immediately(self, api):
        """PRD §3.4: "When `allocated_qty` reaches the full `quantity` —
        whether through an explicit allocate call, an ops-run backfill, or a
        recompute after a release — the order moves `SUBMITTED` → `ALLOCATED`."
        PRD §2.8: "A bucket's `available_count` is always its `standing_count`
        minus its `reserved_count`; allocation, consignment delivery, tag
        sales, and culls all draw against this figure."

        Design: Corner/consistency_model/immediate_consistency_after_allocate
        """
        ctx = setup_submitted_order(quantity=12, unit_price_cents=400, H_6_7=50)
        allocate_order(ctx["order"]["id"], 12, ctx["order"]["version"])
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["allocated_qty"] == 12
        assert order_now["status"] == "ALLOCATED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["reserved_count"] == 12
        assert bucket["available_count"] == 38  # 50 - 12
