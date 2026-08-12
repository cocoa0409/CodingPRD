"""Harvest ticket guards: block state, crew state, double booking, cut caps,
block alignment, void restrictions, and the post/void compensating reversal."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    FM,
    OWNER,
    advance_block_to,
    advance_season_to,
    allocate_order,
    assert_bucket_tree_conservation,
    bucket_of,
    create_block,
    create_buyer,
    create_crop_lot,
    create_crew,
    create_draft_order,
    create_season,
    get_success_data,
    list_order_allocations,
    post_ticket,
    set_clock,
    setup_allocated_order,
    setup_booking_season,
    setup_harvest_with_crew,
    setup_loaded_allocation,
    setup_season_with_block_and_lot,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    make_buyer_headers,
    make_crew_lead_headers,
)


class TestTicketBlockRotationGate:
    def _setup_growing_block(self):
        """Season in HARVEST with the block advanced only to GROWING and a
        live allocation of 10 against its lot."""
        ctx = setup_booking_season(H_6_7=300)
        advance_block_to(ctx["block"]["id"], "GROWING")
        buyer = create_buyer()
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=10, unit_price_cents=400,
        )
        order = submit_order(order["id"], buyer["id"])
        allocate_order(order["id"], 10, order["version"])
        allocation = list_order_allocations(order["id"])[0]
        set_clock(CLOCK["HARVEST_DAY"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        crew = create_crew(ctx["season"]["id"], crew_code="C-1", size=5)
        ctx.update({"buyer": buyer, "order": order,
                    "allocation": allocation, "crew": crew})
        return ctx

    def test_ticket_on_growing_block_rejected(self, api):
        """PRD §3.5: "The block's `rotation_state` must be `HARVESTABLE`
        (`ERR_BLOCK_NOT_HARVESTABLE`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/ticket_gated_by_block_rotation_state
        """
        ctx = self._setup_growing_block()
        resp = api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 8,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 5}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_HARVESTABLE)

    def test_rejected_ticket_leaves_inventory_untouched(self, api):
        """PRD §3.5: "The block's `rotation_state` must be `HARVESTABLE`
        (`ERR_BLOCK_NOT_HARVESTABLE`, HTTP 409)."
        PRD §3.5: "A posted ticket moves real inventory. For each line, the
        allocation's `cut_qty` grows by the line's `cut_count`, and an
        allocation whose `cut_qty` reaches its full `quantity` moves `RESERVED`
        → `CUT`."

        Design: Difficulty/cross_entity_state_dependency/ticket_gated_by_block_rotation_state
        """
        ctx = self._setup_growing_block()
        api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 8,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 5}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        data, meta = validate_paginated(
            api.list_tickets(FM, params={"crew_id": ctx["crew"]["id"]})
        )
        assert meta["total_count"] == 0, "no ticket persisted"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 300
        alloc_now = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], FM)
        )
        assert alloc_now["cut_qty"] == 0


class TestTemporalPriorityOverConstraint:
    def _setup(self):
        return setup_harvest_with_crew(quantity=10, unit_price_cents=400,
                                       H_6_7=300, crew_size=5)

    def test_outside_window_beats_cut_overflow(self, api):
        """PRD §2.6: "ninth, temporal window checks
        (`ERR_OUTSIDE_HARVEST_WINDOW`, `ERR_OUTSIDE_SHIPPING_WINDOW`); tenth,
        referential business rules such as block harvestability, block
        occupancy, u-cut designation, crew activity, buyer standing, and
        ticket-block alignment; eleventh, business constraints such as
        inventory sufficiency, capacity, double-booking, and dock-window
        conflicts; and twelfth, fiscal checks (`ERR_CREDIT_LIMIT_EXCEEDED`).
        Later checks never mask an earlier failure."
        PRD §3.5: "The `work_date` must fall within the season's harvest
        window, both boundary dates inclusive, else
        `ERR_OUTSIDE_HARVEST_WINDOW` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/ticket_outside_window_and_overcut_temporal_wins
        """
        ctx = self._setup()
        resp = api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-10-20",  # outside 2026-11-01..2026-11-25
                "hours_worked": 8,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 999}],  # also exceeds remainder 10
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_HARVEST_WINDOW)

    def test_rejected_ticket_persists_nothing(self, api):
        """PRD §3.5: "The `work_date` must fall within the season's harvest
        window, both boundary dates inclusive, else
        `ERR_OUTSIDE_HARVEST_WINDOW` (HTTP 422)."
        PRD §3.5: "The ticket list filters by `crew_id` and `block_id`, and a
        crew lead sees only its own crew's tickets."

        Design: Difficulty/priority_pair_validation_conflict/ticket_outside_window_and_overcut_temporal_wins
        """
        ctx = self._setup()
        api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-10-20",
                "hours_worked": 8,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 999}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        data, meta = validate_paginated(
            api.list_tickets(FM, params={"crew_id": ctx["crew"]["id"]})
        )
        assert meta["total_count"] == 0
        alloc_now = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], FM)
        )
        assert alloc_now["cut_qty"] == 0


class TestCrewDoubleBooking:
    def _setup(self):
        return setup_harvest_with_crew(quantity=20, unit_price_cents=400,
                                       H_6_7=300, crew_size=5)

    def test_same_crew_same_work_date_rejected(self, api):
        """PRD §3.5: "a crew may hold at most one `POSTED` ticket per calendar
        date — whole-day occupation with date-equality semantics — with a
        second ticket on the same `work_date` rejected as
        `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/crew_whole_day_double_booking
        """
        ctx = self._setup()
        post_ticket(
            ctx["crew"], ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 5}],
            work_date="2026-11-05", hours_worked=8,
        )
        resp = api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 5}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)

    def test_same_crew_next_day_accepted(self, api):
        """PRD §3.5: "a crew may hold at most one `POSTED` ticket per calendar
        date — whole-day occupation with date-equality semantics — with a
        second ticket on the same `work_date` rejected as
        `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."
        PRD §3.5: "The bucket behind each line loses the cut trees from
        `standing_count`, releases them from `reserved_count`, and accrues them
        into `cut_cumulative`."

        Design: Difficulty/resource_temporal_overlap/crew_whole_day_double_booking
        """
        ctx = self._setup()
        post_ticket(
            ctx["crew"], ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 5}],
            work_date="2026-11-05", hours_worked=8,
        )
        resp = api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 5}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)
        next_day = post_ticket(
            ctx["crew"], ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 5}],
            work_date="2026-11-06", hours_worked=4,
        )
        assert next_day["status"] == "POSTED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["cut_cumulative"] == 10, (
            "rejected ticket contributed nothing"
        )


class TestCutRemainderCap:
    def _setup(self):
        return setup_harvest_with_crew(quantity=10, unit_price_cents=400,
                                       H_6_7=50, crew_size=3)

    def test_cut_beyond_remainder_rejected(self, api):
        """PRD §3.5: "no line may cut more than its allocation's uncut
        remainder — the allocation's `quantity` minus its `cut_qty` — else
        `ERR_CUT_EXCEEDS_ALLOCATION` (HTTP 422)."

        Design: Corner/validations/cut_beyond_allocation_remainder_rejected
        """
        ctx = self._setup()
        resp = api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 11}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CUT_EXCEEDS_ALLOCATION)
        data, meta = validate_paginated(
            api.list_tickets(FM, params={"crew_id": ctx["crew"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_cut_exactly_remainder_accepted(self, api):
        """PRD §3.5: "no line may cut more than its allocation's uncut
        remainder — the allocation's `quantity` minus its `cut_qty` — else
        `ERR_CUT_EXCEEDS_ALLOCATION` (HTTP 422)."
        PRD §3.5: "For each line, the allocation's `cut_qty` grows by the
        line's `cut_count`, and an allocation whose `cut_qty` reaches its full
        `quantity` moves `RESERVED` → `CUT`. The bucket behind each line loses
        the cut trees from `standing_count`, releases them from
        `reserved_count`, and accrues them into `cut_cumulative`."

        Design: Corner/validations/cut_beyond_allocation_remainder_rejected
        """
        ctx = self._setup()
        ticket = post_ticket(
            ctx["crew"], ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 10}],
            work_date="2026-11-06", hours_worked=4,
        )
        assert ticket["status"] == "POSTED"
        alloc_now = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], FM)
        )
        assert alloc_now["status"] == "CUT"
        assert alloc_now["cut_qty"] == 10
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 40
        assert bucket["reserved_count"] == 0


class TestTicketBlockMismatch:
    def _setup_two_blocks(self):
        """Two HARVESTABLE blocks; the order's waterfall fills entirely from
        the older (2018) lot on block B-2."""
        season = create_season()
        blk1 = create_block(season["id"], block_code="B-1", acreage=5.0)
        create_crop_lot(blk1["id"], planted_year=2020, H_6_7=40)
        advance_block_to(blk1["id"], "HARVESTABLE")
        blk2 = create_block(season["id"], block_code="B-2", acreage=6.0)
        lot2 = create_crop_lot(blk2["id"], planted_year=2018, H_6_7=60)
        advance_block_to(blk2["id"], "HARVESTABLE")
        set_clock(CLOCK["BOOKING_OPEN"])
        advance_season_to(season["id"], "BOOKING")
        buyer = create_buyer()
        order = create_draft_order(season["id"], buyer["id"], quantity=10,
                                   unit_price_cents=400)
        order = submit_order(order["id"], buyer["id"])
        allocate_order(order["id"], 10, order["version"])
        b2 = bucket_of(lot2["id"], "H_6_7")
        allocs = list_order_allocations(order["id"], bucket_id=b2["id"])
        assert len(allocs) == 1, "waterfall filled entirely from the older lot"
        set_clock(CLOCK["HARVEST_DAY"])
        advance_season_to(season["id"], "HARVEST")
        crew = create_crew(season["id"], crew_code="C-1", size=3)
        return season, blk1, allocs[0], crew

    def test_line_from_other_block_rejected(self, api):
        """PRD §3.5: "Every line's allocation must belong to a crop lot of the
        ticket's own block, else `ERR_TICKET_BLOCK_MISMATCH` (HTTP 422), and no
        line may cut more than its allocation's uncut remainder — the
        allocation's `quantity` minus its `cut_qty` — else
        `ERR_CUT_EXCEEDS_ALLOCATION` (HTTP 422)."

        Design: Corner/validations/ticket_line_block_mismatch_rejected
        """
        _season, blk1, alloc_b2, crew = self._setup_two_blocks()
        resp = api.create_ticket(
            {
                "crew_id": crew["id"],
                "block_id": blk1["id"],  # ticket names B-1, allocation is B-2's
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": alloc_b2["id"], "cut_count": 2}],
            },
            make_crew_lead_headers(crew["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TICKET_BLOCK_MISMATCH)

    def test_rejected_mismatch_cuts_nothing(self, api):
        """PRD §3.5: "Every line's allocation must belong to a crop lot of the
        ticket's own block, else `ERR_TICKET_BLOCK_MISMATCH` (HTTP 422), and no
        line may cut more than its allocation's uncut remainder — the
        allocation's `quantity` minus its `cut_qty` — else
        `ERR_CUT_EXCEEDS_ALLOCATION` (HTTP 422)."

        Design: Corner/validations/ticket_line_block_mismatch_rejected
        """
        _season, blk1, alloc_b2, crew = self._setup_two_blocks()
        api.create_ticket(
            {
                "crew_id": crew["id"],
                "block_id": blk1["id"],
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": alloc_b2["id"], "cut_count": 2}],
            },
            make_crew_lead_headers(crew["id"]),
        )
        data, meta = validate_paginated(
            api.list_tickets(FM, params={"crew_id": crew["id"]})
        )
        assert meta["total_count"] == 0
        alloc_now = get_success_data(api.get_allocation(alloc_b2["id"], FM))
        assert alloc_now["cut_qty"] == 0


class TestCrewActivityGate:
    def test_laid_off_crew_rejected(self, api):
        """PRD §3.5: "The crew must be `ACTIVE` (`ERR_CREW_NOT_ACTIVE`, HTTP
        409), and a crew may hold at most one `POSTED` ticket per calendar date
        — whole-day occupation with date-equality semantics — with a second
        ticket on the same `work_date` rejected as `ERR_CREW_DOUBLE_BOOKED`
        (HTTP 409)."
        PRD §3.5: "A crew is born `ACTIVE` and can be moved to terminal
        `LAID_OFF` by the farm manager."

        Design: Corner/validations/ticket_by_laid_off_crew_rejected
        """
        ctx = setup_harvest_with_crew(quantity=10, unit_price_cents=400,
                                      H_6_7=50, crew_size=3)
        crew2 = create_crew(ctx["season"]["id"], crew_code="C-2", size=3)
        get_success_data(api.lay_off_crew(ctx["crew"]["id"], FM))
        resp = api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 2}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_ACTIVE)

    def test_other_active_crew_unaffected_same_day(self, api):
        """PRD §3.5: "a crew may hold at most one `POSTED` ticket per calendar
        date — whole-day occupation with date-equality semantics — with a
        second ticket on the same `work_date` rejected as
        `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

        Design: Corner/validations/ticket_by_laid_off_crew_rejected
        """
        ctx = setup_harvest_with_crew(quantity=10, unit_price_cents=400,
                                      H_6_7=50, crew_size=3)
        crew2 = create_crew(ctx["season"]["id"], crew_code="C-2", size=3)
        get_success_data(api.lay_off_crew(ctx["crew"]["id"], FM))
        api.create_ticket(
            {
                "crew_id": ctx["crew"]["id"],
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 2}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        ticket = post_ticket(
            crew2, ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 2}],
            work_date="2026-11-05", hours_worked=4,
        )
        assert ticket["status"] == "POSTED", "double-booking is per-crew"


class TestCrewLeadOwnership:
    def test_ticket_for_other_crew_forbidden(self, api):
        """PRD §2.1: "A crew lead may post a harvest ticket only when the
        ticket's `crew_id` equals `X-User-ID`, and sees only its own crew's
        tickets; violations are rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/crewlead_ticket_for_other_crew_forbidden
        """
        ctx = setup_harvest_with_crew(quantity=6, unit_price_cents=400,
                                      H_6_7=50, crew_size=3)
        crew2 = create_crew(ctx["season"]["id"], crew_code="C-2", size=3)
        resp = api.create_ticket(
            {
                "crew_id": crew2["id"],  # caller is crew 1's lead
                "block_id": ctx["block"]["id"],
                "work_date": "2026-11-05",
                "hours_worked": 4,
                "lines": [{"allocation_id": ctx["allocation"]["id"],
                           "cut_count": 1}],
            },
            make_crew_lead_headers(ctx["crew"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        data, meta = validate_paginated(
            api.list_tickets(FM, params={"crew_id": crew2["id"]})
        )
        assert meta["total_count"] == 0

    def test_crew_lead_cannot_create_crews(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role, and
        an attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/api/crews` | Hire a crew | FarmManager |"

        Design: Corner/rbac/crewlead_cannot_create_crews
        """
        season = create_season()
        resp = api.create_crew(
            {"season_id": season["id"], "crew_code": "C-9", "size": 4},
            make_crew_lead_headers("00000000-0000-4000-8000-0000000000ff"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        data, meta = validate_paginated(
            api.list_crews(FM, params={"season_id": season["id"]})
        )
        assert meta["total_count"] == 0


class TestTicketVoidConservation:
    def _setup(self):
        return setup_harvest_with_crew(quantity=100, unit_price_cents=400,
                                       H_6_7=300, crew_size=5)

    def test_posted_ticket_moves_counters_consistently(self, api):
        """PRD §3.5: "A posted ticket moves real inventory. For each line, the
        allocation's `cut_qty` grows by the line's `cut_count`, and an
        allocation whose `cut_qty` reaches its full `quantity` moves `RESERVED`
        → `CUT`. The bucket behind each line loses the cut trees from
        `standing_count`, releases them from `reserved_count`, and accrues them
        into `cut_cumulative`."

        Design: Difficulty/compensating_invariant/ticket_post_void_bucket_tree_conservation
        """
        ctx = self._setup()
        ticket = post_ticket(
            ctx["crew"], ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 40}],
        )
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 260  # 300 - 40
        assert bucket["reserved_count"] == 60   # 100 - 40
        assert bucket["cut_cumulative"] == 40
        assert_bucket_tree_conservation(bucket)  # 300 == 260 + 40
        alloc_now = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], FM)
        )
        assert alloc_now["cut_qty"] == 40
        assert alloc_now["status"] == "RESERVED", "partial cut stays RESERVED"

    def test_void_restores_pre_ticket_snapshot(self, api):
        """PRD §3.5: "Voiding is a full compensating reversal: each line's
        `cut_count` is deducted from its allocation's `cut_qty` (an allocation
        that drops below full cut reverts from `CUT` to `RESERVED`), and each
        bucket's `standing_count`, `reserved_count`, and `cut_cumulative` are
        restored by the line's count. The ticket itself moves to terminal
        `VOIDED`."

        Design: Difficulty/compensating_invariant/ticket_post_void_bucket_tree_conservation
        """
        ctx = self._setup()
        ticket = post_ticket(
            ctx["crew"], ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 40}],
        )
        voided = get_success_data(api.void_ticket(ticket["id"], FM))
        assert voided["status"] == "VOIDED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 300, "identical to pre-ticket"
        assert bucket["reserved_count"] == 100
        assert bucket["cut_cumulative"] == 0
        assert_bucket_tree_conservation(bucket)  # zero drift
        alloc_now = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], FM)
        )
        assert alloc_now["status"] == "RESERVED"
        assert alloc_now["cut_qty"] == 0


class TestVoidWithLoadedLine:
    def test_void_of_ticket_with_loaded_allocation_rejected(self, api):
        """PRD §3.5: "A `FarmManager` may void a `POSTED` ticket, but only
        while the season remains in `HARVEST` and only when no line's
        allocation has already been loaded onto a truck; either violation
        yields `ERR_TICKET_NOT_VOIDABLE` (HTTP 409)."

        Design: Corner/validations/void_ticket_with_loaded_line_rejected
        """
        ctx = setup_loaded_allocation(quantity=2, unit_price_cents=400,
                                      H_6_7=50, crew_size=3, capacity_units=20)
        assert ctx["allocation"]["status"] == "LOADED"
        resp = api.void_ticket(ctx["ticket"]["id"], FM)
        validate_error(resp, ApiErrorId.ERR_TICKET_NOT_VOIDABLE)

    def test_rejected_void_preserves_ticket_and_bucket(self, api):
        """PRD §3.5: "A `FarmManager` may void a `POSTED` ticket, but only
        while the season remains in `HARVEST` and only when no line's
        allocation has already been loaded onto a truck; either violation
        yields `ERR_TICKET_NOT_VOIDABLE` (HTTP 409)."
        PRD §3.5: "The bucket behind each line loses the cut trees from
        `standing_count`, releases them from `reserved_count`, and accrues them
        into `cut_cumulative`."

        Design: Corner/validations/void_ticket_with_loaded_line_rejected
        """
        ctx = setup_loaded_allocation(quantity=2, unit_price_cents=400,
                                      H_6_7=50, crew_size=3, capacity_units=20)
        api.void_ticket(ctx["ticket"]["id"], FM)
        ticket_now = get_success_data(api.get_ticket(ctx["ticket"]["id"], FM))
        assert ticket_now["status"] == "POSTED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 48  # 50 - 2 cut stays cut
