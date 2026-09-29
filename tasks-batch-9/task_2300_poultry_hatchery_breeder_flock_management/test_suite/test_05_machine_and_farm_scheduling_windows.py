"""Two overlap tests with deliberately opposite endpoint semantics: the closed
machine occupancy window of setter planning and the half-open farm placement cycle
of order confirmation.
"""

from test_helpers import (
    ApiClient,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    ApiErrorId,
    OrderStatus,
    SetterLoadStatus,
    UnitType,
    assert_grower_farm,
    assert_placement_order,
    assert_setter_load,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The instant the first load's occupancy of its machine ends: set + 504h + 12h.
OCCUPANCY_ENDS_AT = "2026-08-23T06:00:00Z"


def _machine_pair_with_one_load(api: ApiClient):
    """Two setter machines, one of which already carries a load planned for 18:00."""
    fx.set_clock(api, fx.CLOCK_SETUP)
    unit_1 = fx.create_unit(api, code="U1", unit_type=UnitType.SETTER.value)
    unit_2 = fx.create_unit(api, code="U2", unit_type=UnitType.SETTER.value)
    profile = fx.create_profile(api)
    first = get_success_data(
        api.create_setter_load(
            f.setter_load_payload(unit_1["id"], profile["id"], "2026-08-01T18:00:00Z"),
            INCUBATION_OPERATOR,
        ),
        201,
    )
    return {"unit_1": unit_1, "unit_2": unit_2, "profile": profile, "first": first}


def _plan_on(api: ApiClient, ctx, unit_key: str, planned_set_at: str):
    return api.create_setter_load(
        f.setter_load_payload(ctx[unit_key]["id"], ctx["profile"]["id"], planned_set_at),
        INCUBATION_OPERATOR,
    )


class TestSetterMachineWindow:
    """The machine window is closed, so touching endpoints conflict."""

    def test_load_starting_exactly_when_occupancy_ends_conflicts(self, api):
        """PRD 3.5: "The two conflict when the new interval's start is at or before the
        existing interval's end **and** the existing interval's start is at or before the
        new interval's end. Touching endpoints therefore *do* conflict: a load planned to
        start at exactly the instant an existing occupancy ends is rejected with
        `ERR_UNIT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/setter_unit_closed_window_touch_conflicts
        """
        ctx = _machine_pair_with_one_load(api)

        response = _plan_on(api, ctx, "unit_1", OCCUPANCY_ENDS_AT)

        validate_error(response, ApiErrorId.ERR_UNIT_WINDOW_CONFLICT, 409)

    def test_load_starting_one_hour_later_is_accepted(self, api):
        """PRD 3.5: "Each existing load of the same machine occupies that machine from its
        own `planned_set_at` until its `planned_set_at` plus its profile's `total_hours`
        plus a sanitation turnaround of 12 hours."

        Design: Difficulty/resource_temporal_overlap/setter_unit_closed_window_touch_conflicts
        """
        ctx = _machine_pair_with_one_load(api)

        response = _plan_on(api, ctx, "unit_1", "2026-08-23T07:00:00Z")

        planned = validate_success(response, 201)
        assert_setter_load(
            planned,
            unit_id=ctx["unit_1"]["id"],
            status=SetterLoadStatus.PLANNED.value,
            planned_set_at="2026-08-23T07:00:00Z",
        )

    def test_window_check_is_scoped_to_one_machine(self, api):
        """PRD 3.5: "The check runs against every load of that machine in `PLANNED`,
        `INCUBATING` or `CANDLED`; loads in `ABORTED` or `TRANSFERRED` have released the
        machine and are ignored."

        Design: Difficulty/resource_temporal_overlap/setter_unit_closed_window_touch_conflicts
        """
        ctx = _machine_pair_with_one_load(api)
        validate_error(
            _plan_on(api, ctx, "unit_1", OCCUPANCY_ENDS_AT),
            ApiErrorId.ERR_UNIT_WINDOW_CONFLICT,
            409,
        )
        validate_success(_plan_on(api, ctx, "unit_1", "2026-08-23T07:00:00Z"), 201)

        on_other_machine = _plan_on(api, ctx, "unit_2", OCCUPANCY_ENDS_AT)

        second_machine_load = validate_success(on_other_machine, 201)
        assert_setter_load(
            second_machine_load,
            unit_id=ctx["unit_2"]["id"],
            status=SetterLoadStatus.PLANNED.value,
        )
        _rows, meta_1 = validate_paginated(
            api.list_setter_loads(INCUBATION_OPERATOR, {"unit_id": ctx["unit_1"]["id"]})
        )
        assert meta_1["total_count"] == 2, (
            f"the first machine carries two loads, got {meta_1['total_count']}"
        )
        _rows, meta_2 = validate_paginated(
            api.list_setter_loads(INCUBATION_OPERATOR, {"unit_id": ctx["unit_2"]["id"]})
        )
        assert meta_2["total_count"] == 1, (
            f"the second machine carries one load, got {meta_2['total_count']}"
        )


class TestFarmPlacementCycle:
    """The farm cycle is half-open, so touching endpoints do not conflict."""

    def _farm_with_confirmed_order(self, api: ApiClient):
        fx.set_clock(api, fx.CLOCK_SETUP)
        farm = fx.cleared_farm(api, code="FM1", capacity_chicks=8000)
        first = fx.confirmed_order(
            api,
            farm["id"],
            requested_chicks=5000,
            requested_placement_date="2026-08-22T00:00:00Z",
        )
        return {"farm": farm, "first": first}

    def test_overlapping_cycles_sum_against_farm_capacity(self, api):
        """PRD 3.8: "Gather every other order of the same farm in `CONFIRMED`,
        `PARTIALLY_FULFILLED` or `FULFILLED` whose cycle intersects the new order's cycle,
        sum their `requested_chicks`, add the new order's `requested_chicks`, and reject
        with `ERR_FARM_CAPACITY_EXCEEDED` when that total is strictly greater than the
        farm's `capacity_chicks`."

        Design: Difficulty/resource_temporal_overlap/farm_cycle_halfopen_aggregate_capacity
        """
        ctx = self._farm_with_confirmed_order(api)
        overlapping = fx.requested_order(
            api,
            ctx["farm"]["id"],
            requested_chicks=4250,
            requested_placement_date="2026-08-23T00:00:00Z",
        )

        response = api.confirm_placement_order(overlapping["id"], HATCHERY_MANAGER)

        validate_error(response, ApiErrorId.ERR_FARM_CAPACITY_EXCEEDED, 422)
        assert_placement_order(
            fx.read_order(api, overlapping["id"]), status=OrderStatus.REQUESTED.value
        )

    def test_cycle_starting_exactly_where_another_ends_consumes_no_capacity(self, api):
        """PRD 3.8: "The farm's placement cycle for an order is the **half-open** interval
        that starts at the order's `requested_placement_date` and ends 21 days later,
        excluding the end instant." And: "Because the interval is half-open, touching
        endpoints do **not** conflict: an order placed exactly 21 days after an existing
        one shares no time with it and consumes none of its capacity."

        Design: Difficulty/resource_temporal_overlap/farm_cycle_halfopen_aggregate_capacity
        """
        ctx = self._farm_with_confirmed_order(api)
        touching = fx.requested_order(
            api,
            ctx["farm"]["id"],
            requested_chicks=3000,
            requested_placement_date="2026-09-12T00:00:00Z",
        )

        response = api.confirm_placement_order(touching["id"], HATCHERY_MANAGER)

        confirmed = validate_success(response, 200)
        assert_placement_order(
            confirmed, status=OrderStatus.CONFIRMED.value, requested_chicks=3000
        )

    def test_orders_individually_within_capacity_can_breach_it_together(self, api):
        """PRD 3.8: "Note also that orders which are individually well within capacity can
        still breach it together."

        Design: Difficulty/resource_temporal_overlap/farm_cycle_halfopen_aggregate_capacity
        """
        ctx = self._farm_with_confirmed_order(api)
        second = fx.requested_order(
            api,
            ctx["farm"]["id"],
            requested_chicks=4250,
            requested_placement_date="2026-08-23T00:00:00Z",
        )
        third = fx.requested_order(
            api,
            ctx["farm"]["id"],
            requested_chicks=3000,
            requested_placement_date="2026-09-12T00:00:00Z",
        )
        fourth = fx.requested_order(
            api,
            ctx["farm"]["id"],
            requested_chicks=3000,
            requested_placement_date="2026-09-11T00:00:00Z",
        )
        validate_error(
            api.confirm_placement_order(second["id"], HATCHERY_MANAGER),
            ApiErrorId.ERR_FARM_CAPACITY_EXCEEDED,
            422,
        )
        validate_success(api.confirm_placement_order(third["id"], HATCHERY_MANAGER), 200)

        response = api.confirm_placement_order(fourth["id"], HATCHERY_MANAGER)

        validate_error(response, ApiErrorId.ERR_FARM_CAPACITY_EXCEEDED, 422)
        for order_id, expected_status in (
            (ctx["first"]["id"], OrderStatus.CONFIRMED.value),
            (second["id"], OrderStatus.REQUESTED.value),
            (third["id"], OrderStatus.CONFIRMED.value),
            (fourth["id"], OrderStatus.REQUESTED.value),
        ):
            assert_placement_order(
                fx.read_order(api, order_id), status=expected_status
            )
        assert_grower_farm(
            get_success_data(
                api.get_grower_farm(ctx["farm"]["id"], HATCHERY_MANAGER), 200
            ),
            capacity_chicks=8000,
        )
        _rows, meta = validate_paginated(
            api.list_placement_orders(HATCHERY_MANAGER, {"farm_id": ctx["farm"]["id"]})
        )
        assert meta["total_count"] == 4, (
            f"all four orders remain on the farm, got {meta['total_count']}"
        )
