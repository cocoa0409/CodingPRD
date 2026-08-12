"""Load building, capacity enforcement, auto-close, dock windows, shipping."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    FM,
    OWNER,
    advance_block_to,
    advance_season_to,
    allocate_order,
    bucket_of,
    create_buyer,
    create_crew,
    create_draft_order,
    create_load,
    create_season,
    get_success_data,
    list_order_allocations,
    post_ticket,
    set_clock,
    setup_booking_season,
    setup_cut_allocation,
    setup_harvest_with_crew,
    submit_order,
    validate_error,
    validate_paginated,
    api_client,
    make_buyer_headers,
)


class TestOrderAutoClose:
    def test_final_line_flips_allocation_to_loaded(self, api):
        """PRD §3.6: "Each accepted line grows the allocation's `loaded_qty`,
        and an allocation whose `loaded_qty` reaches its `cut_qty` moves `CUT`
        → `LOADED`."
        PRD §3.6: "Capacity is enforced in abstract tree-units: each height
        class weighs 1 unit for `H_4_5`, 2 for `H_5_6`, 3 for `H_6_7`, 5 for
        `H_7_8`, 7 for `H_8_9`, and 9 for `H_9_PLUS`, and each appended line
        contributes its `quantity` multiplied by the weight of its allocation's
        height class — recorded on the line as its `units`."

        Design: Corner/state_machines/order_auto_closes_when_all_allocations_loaded
        """
        ctx = setup_cut_allocation(quantity=2, height_class="H_7_8",
                                   unit_price_cents=900, crew_size=3, H_7_8=50)
        load = create_load(ctx["season"]["id"], capacity_units=20)
        load = get_success_data(
            api.add_load_line(load["id"], ctx["allocation"]["id"], 2, FM)
        )
        assert load["total_units"] == 10  # 2 * weight(H_7_8)=5
        alloc_now = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], FM)
        )
        assert alloc_now["status"] == "LOADED"
        assert alloc_now["loaded_qty"] == 2

    def test_order_closes_and_exposure_relieved(self, api):
        """PRD §3.6: "When an order is fully allocated and every one of its
        non-released allocations has reached `LOADED`, the order closes itself:
        it moves `ALLOCATED` → `CLOSED` and the buyer's `exposure_cents` is
        relieved of the order's `invoice_total_cents`."

        Design: Corner/state_machines/order_auto_closes_when_all_allocations_loaded
        """
        ctx = setup_cut_allocation(quantity=2, height_class="H_7_8",
                                   unit_price_cents=900, crew_size=3, H_7_8=50)
        load = create_load(ctx["season"]["id"], capacity_units=20)
        get_success_data(
            api.add_load_line(load["id"], ctx["allocation"]["id"], 2, FM)
        )
        order_now = get_success_data(api.get_order(ctx["order"]["id"], FM))
        assert order_now["status"] == "CLOSED"
        buyer_now = get_success_data(
            api.get_buyer_account(ctx["buyer"]["id"], OWNER)
        )
        assert buyer_now["exposure_cents"] == 0  # invoice 1800 removed


class TestLoadCapacity:
    def _setup(self):
        ctx = setup_cut_allocation(quantity=3, height_class="H_7_8",
                                   unit_price_cents=900, crew_size=3, H_7_8=50)
        load = create_load(ctx["season"]["id"], capacity_units=10)
        return ctx, load

    def test_exact_capacity_fill_accepted(self, api):
        """PRD §3.6: "A line that would push the load's `total_units` above
        `capacity_units` is rejected with `ERR_LOAD_OVER_CAPACITY` (HTTP 422);
        a load filled to exactly capacity is legal."

        Design: Corner/calculations/load_capacity_exact_fit_then_overflow
        """
        ctx, load = self._setup()
        load = get_success_data(
            api.add_load_line(load["id"], ctx["allocation"]["id"], 2, FM)
        )
        assert load["total_units"] == 10  # 2 * 5 == capacity 10, equality legal
        assert load["status"] == "BUILDING"

    def test_one_unit_over_capacity_rejected(self, api):
        """PRD §3.6: "A line that would push the load's `total_units` above
        `capacity_units` is rejected with `ERR_LOAD_OVER_CAPACITY` (HTTP 422);
        a load filled to exactly capacity is legal."

        Design: Corner/calculations/load_capacity_exact_fit_then_overflow
        """
        ctx, load = self._setup()
        get_success_data(
            api.add_load_line(load["id"], ctx["allocation"]["id"], 2, FM)
        )
        resp = api.add_load_line(load["id"], ctx["allocation"]["id"], 1, FM)
        validate_error(resp, ApiErrorId.ERR_LOAD_OVER_CAPACITY)  # 15 > 10
        load_now = get_success_data(api.get_load(load["id"], FM))
        assert load_now["total_units"] == 10
        assert load_now["status"] == "BUILDING"
        alloc_now = get_success_data(
            api.get_allocation(ctx["allocation"]["id"], FM)
        )
        assert alloc_now["loaded_qty"] == 2


class TestLoadLineRequiresCut:
    def test_reserved_allocation_cannot_be_loaded(self, api):
        """PRD §3.6: "The allocation must be in `CUT` status with enough
        cut-but-unloaded headroom — the quantity may not exceed the
        allocation's `cut_qty` minus its `loaded_qty` — else
        `ERR_ALLOCATION_NOT_CUT` (HTTP 409)."

        Design: Corner/validations/load_line_from_reserved_allocation_rejected
        """
        ctx = setup_harvest_with_crew(quantity=4, unit_price_cents=400,
                                      H_6_7=50, crew_size=3)
        assert ctx["allocation"]["status"] == "RESERVED"
        load = create_load(ctx["season"]["id"], capacity_units=50)
        resp = api.add_load_line(load["id"], ctx["allocation"]["id"], 4, FM)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_CUT)

    def test_rejected_line_leaves_no_trace(self, api):
        """PRD §3.6: "A load is born `BUILDING` with empty `lines` and
        `total_units` at zero; the load list filters by `season_id`."
        PRD §3.6: "The allocation must be in `CUT` status with enough
        cut-but-unloaded headroom — the quantity may not exceed the
        allocation's `cut_qty` minus its `loaded_qty` — else
        `ERR_ALLOCATION_NOT_CUT` (HTTP 409)."

        Design: Corner/validations/load_line_from_reserved_allocation_rejected
        """
        ctx = setup_harvest_with_crew(quantity=4, unit_price_cents=400,
                                      H_6_7=50, crew_size=3)
        load = create_load(ctx["season"]["id"], capacity_units=50)
        api.add_load_line(load["id"], ctx["allocation"]["id"], 4, FM)
        load_now = get_success_data(api.get_load(load["id"], FM))
        assert load_now["total_units"] == 0
        assert load_now["lines"] == []


class TestDockWindowBuffer:
    def _harvest_season(self):
        ctx = setup_booking_season(H_6_7=50)
        set_clock(CLOCK["HARVEST_DAY"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        return ctx

    def test_exact_thirty_minute_gap_accepted(self, api):
        """PRD §3.6: "Dock scheduling also enforces a thirty-minute buffer
        between trucks: a new load conflicts with any other non-cancelled load
        of the season when the new window's start falls before the other load's
        window end plus thirty minutes and the other load's window start falls
        before the new window's end plus thirty minutes; a gap of exactly
        thirty minutes between windows is permitted and is not a conflict."

        Design: Difficulty/resource_temporal_overlap/dock_pickup_window_thirty_minute_buffer
        """
        ctx = self._harvest_season()
        create_load(ctx["season"]["id"], carrier_name="Carrier A",
                    pickup_window_start="2026-11-20T09:00:00Z",
                    pickup_window_end="2026-11-20T10:00:00Z")
        load_b = create_load(ctx["season"]["id"], carrier_name="Carrier B",
                             pickup_window_start="2026-11-20T10:30:00Z",
                             pickup_window_end="2026-11-20T11:30:00Z")
        assert load_b["status"] == "BUILDING", "exactly-30-minute gap is legal"

    def test_twenty_nine_minute_gap_rejected(self, api):
        """PRD §3.6: "Conflicts are rejected with `ERR_DOCK_WINDOW_CONFLICT`
        (HTTP 409). A load is born `BUILDING` with empty `lines` and
        `total_units` at zero; the load list filters by `season_id`."

        Design: Difficulty/resource_temporal_overlap/dock_pickup_window_thirty_minute_buffer
        """
        ctx = self._harvest_season()
        create_load(ctx["season"]["id"], carrier_name="Carrier A",
                    pickup_window_start="2026-11-20T09:00:00Z",
                    pickup_window_end="2026-11-20T10:00:00Z")
        create_load(ctx["season"]["id"], carrier_name="Carrier B",
                    pickup_window_start="2026-11-20T10:30:00Z",
                    pickup_window_end="2026-11-20T11:30:00Z")
        resp = api.create_load(
            {
                "season_id": ctx["season"]["id"],
                "carrier_name": "Carrier C",
                "capacity_units": 100,
                "pickup_window_start": "2026-11-20T10:29:00Z",
                "pickup_window_end": "2026-11-20T11:00:00Z",
            },
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)
        data, meta = validate_paginated(
            api.list_loads(FM, params={"season_id": ctx["season"]["id"]})
        )
        assert meta["total_count"] == 2, "rejected load never persisted"


class TestShipWindowBoundary:
    def _setup_two_loaded_loads(self):
        """Two orders (8 and 4 trees of H_6_7) fully cut and loaded; season
        ready to advance to SHIPPING."""
        ctx = setup_booking_season(H_6_7=200)
        advance_block_to(ctx["block"]["id"], "HARVESTABLE")
        buyer = create_buyer()
        orders = []
        for quantity in (8, 4):
            order = create_draft_order(
                ctx["season"]["id"], buyer["id"], quantity=quantity,
                unit_price_cents=400,
            )
            order = submit_order(order["id"], buyer["id"])
            allocate_order(order["id"], quantity, order["version"])
            orders.append(order)
        allocs = [list_order_allocations(o["id"])[0] for o in orders]
        set_clock(CLOCK["HARVEST_DAY"])
        advance_season_to(ctx["season"]["id"], "HARVEST")
        crew = create_crew(ctx["season"]["id"], crew_code="C-1", size=5)
        post_ticket(crew, ctx["block"]["id"],
                    [{"allocation_id": allocs[0]["id"], "cut_count": 8}],
                    work_date="2026-11-05", hours_worked=8)
        post_ticket(crew, ctx["block"]["id"],
                    [{"allocation_id": allocs[1]["id"], "cut_count": 4}],
                    work_date="2026-11-06", hours_worked=4)
        load_a = create_load(ctx["season"]["id"], carrier_name="Carrier A",
                             capacity_units=100,
                             pickup_window_start="2026-11-20T09:00:00Z",
                             pickup_window_end="2026-11-20T10:00:00Z")
        get_success_data(api_client.add_load_line(load_a["id"], allocs[0]["id"], 8, FM))
        load_b = create_load(ctx["season"]["id"], carrier_name="Carrier B",
                             capacity_units=50,
                             pickup_window_start="2026-11-21T09:00:00Z",
                             pickup_window_end="2026-11-21T10:00:00Z")
        get_success_data(api_client.add_load_line(load_b["id"], allocs[1]["id"], 4, FM))
        advance_season_to(ctx["season"]["id"], "SHIPPING")
        return ctx, load_a, load_b

    def test_ship_at_window_end_inclusive_succeeds(self, api):
        """PRD §3.6: "while the season is in `SHIPPING` posture and the logical
        clock sits inside the shipping window — both boundary instants
        inclusive — the farm manager ships a `BUILDING` load, moving it to
        terminal `SHIPPED`."

        Design: Difficulty/boundary_precision_check/ship_at_shipping_window_end_inclusive
        """
        _ctx, load_a, _load_b = self._setup_two_loaded_loads()
        set_clock(CLOCK["SHIPPING_WINDOW_END"])  # 2026-12-10T23:59:59Z
        shipped = get_success_data(api.ship_load(load_a["id"], FM))
        assert shipped["status"] == "SHIPPED", "clock == window end is inclusive"

    def test_one_second_past_window_end_rejected(self, api):
        """PRD §3.6: "A clock outside that window fails with
        `ERR_OUTSIDE_SHIPPING_WINDOW`."
        PRD §3.6: "while the season is in `SHIPPING` posture and the logical
        clock sits inside the shipping window — both boundary instants
        inclusive — the farm manager ships a `BUILDING` load, moving it to
        terminal `SHIPPED`."

        Design: Difficulty/boundary_precision_check/ship_at_shipping_window_end_inclusive
        """
        _ctx, load_a, load_b = self._setup_two_loaded_loads()
        set_clock(CLOCK["SHIPPING_WINDOW_END"])
        get_success_data(api.ship_load(load_a["id"], FM))
        set_clock(CLOCK["ONE_SECOND_PAST_SHIPPING_END"])  # 2026-12-11T00:00:00Z
        resp = api.ship_load(load_b["id"], FM)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHIPPING_WINDOW)
        load_b_now = get_success_data(api.get_load(load_b["id"], FM))
        assert load_b_now["status"] == "BUILDING"
