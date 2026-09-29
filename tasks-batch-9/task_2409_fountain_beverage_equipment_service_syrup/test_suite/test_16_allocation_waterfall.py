"""The allocation waterfall: eligibility, pinned order, case packs and hard stops.

Whole cases only, a cap below one case granting nothing, a critical position served
ahead of a low one, the two all-or-nothing refusals, and the three eligibility tests
that silently empty the candidate set.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    add_stop,
    add_telemetry,
    allocate,
    allocation_payload,
    ApiErrorId,
    create_agreement,
    create_outlet,
    create_position,
    create_route,
    create_supply_item,
    create_unit,
    pin_clock,
    read_position,
    read_route,
    read_supply_item,
    run_forecast,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet_and_unit():
    pin_clock(CLOCK)
    outlet = create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    return outlet, unit


def _route_with_one_stop(outlet_id, capacity_units=60):
    route = create_route(
        route_code="RT-01", depot_region_code="R-WEST",
        service_date="2026-08-03T00:00:00Z", van_code="VAN-7",
        capacity_units=capacity_units,
    )
    stop = add_stop(
        route["id"], outlet_id, 1, "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"
    )
    return route, stop


def _forecast_position(outlet, unit, on_hand_units, **item_overrides):
    """One forecast position fed by a single 7000-ounce weekly reading."""
    catalogue_entry = {
        "sku_code": "SKU-COLA",
        "brand_name": "Cola Classic",
        "supply_form": "CARTRIDGE",
        "case_pack_units": 4,
        "ounces_per_unit": 1000,
        "national_allocation_units": 100,
    }
    catalogue_entry.update(item_overrides)
    item = create_supply_item(**catalogue_entry)
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], on_hand_units)
    forecast = run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    return item, position, forecast


class TestCasePackTruncation:
    def test_a_cap_of_five_against_a_four_pack_ships_one_case(self, api):
        """PRD §3.7: "Where both hard stops pass, the grant is computed by taking the
        smallest of three numbers — the position's `requested_units`, the unreserved
        pool and the remaining route capacity — and then truncating that cap downward to
        a whole multiple of the SKU's `case_pack_units`. Partial cases are never
        shipped: a cap of 5 against a case pack of 4 grants 4, and a cap of 3 against a
        case pack of 4 grants 0."

        Design: Corner/calculations/allocation_case_pack_truncation_grants_whole_cases_only
        """
        outlet, unit = _outlet_and_unit()
        item, position, forecast = _forecast_position(
            outlet, unit, 2, supply_form="BAG_IN_BOX", ounces_per_unit=2000
        )
        assert forecast["requested_units"] == 5
        route, stop = _route_with_one_stop(outlet["id"])

        summary = allocate(stop["id"], [position["id"]])
        assert summary["total_allocated_units"] == 4
        assert summary["allocated_position_count"] == 1

        granted = read_position(position["id"])
        assert granted["allocated_units"] == 4
        assert granted["planned_route_stop_id"] == stop["id"]
        assert read_supply_item(item["id"])["reserved_pool_units"] == 4
        assert read_route(route["id"])["committed_units"] == 4

    def test_a_cap_below_one_case_grants_nothing_and_still_succeeds(self, api):
        """PRD §3.7: "Partial cases are never shipped: a cap of 5 against a case pack of
        4 grants 4, and a cap of 3 against a case pack of 4 grants 0. A positive grant
        writes the position's `allocated_units` and points its `planned_route_stop_id` at
        this stop, and raises both the SKU's `reserved_pool_units` and the route's
        `committed_units` by the granted amount. A grant of zero changes nothing: the
        position keeps `allocated_units` at 0 and `planned_route_stop_id` null."

        Design: Corner/calculations/allocation_grant_of_zero_when_the_cap_is_below_one_case
        """
        outlet, unit = _outlet_and_unit()
        item, position, forecast = _forecast_position(
            outlet, unit, 2, supply_form="BAG_IN_BOX", ounces_per_unit=3000
        )
        assert forecast["requested_units"] == 3
        assert forecast["alert_level"] == "LOW"
        route, stop = _route_with_one_stop(outlet["id"])

        summary = allocate(stop["id"], [position["id"]])
        assert summary["total_allocated_units"] == 0

        untouched = read_position(position["id"])
        assert untouched["allocated_units"] == 0
        assert untouched["planned_route_stop_id"] is None
        assert read_supply_item(item["id"])["reserved_pool_units"] == 0
        assert read_route(route["id"])["committed_units"] == 0


class TestWaterfallOrdering:
    def test_the_critical_position_takes_the_capacity_before_the_low_one(self, api):
        """PRD §3.7: "The survivors are then processed in a pinned order: all `CRITICAL`
        positions before all `LOW` ones; within the same alert band, the larger
        `requested_units` first; and where those still tie, the older position first by
        `created_at` ascending." Each grant is then read against what is left: "The
        SKU's unreserved pool is its `national_allocation_units` less its
        `reserved_pool_units`, and the route's remaining capacity is its `capacity_units`
        less its `committed_units`, both read at the moment this position is reached, so
        earlier grants in the same request have already consumed what they took."

        Design: Corner/calculations/allocation_orders_critical_before_low_then_capacity_truncates_the_second_grant
        """
        outlet, unit = _outlet_and_unit()
        cola = create_supply_item(
            sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="CARTRIDGE",
            case_pack_units=3, ounces_per_unit=1000, national_allocation_units=100,
        )
        lemon = create_supply_item(
            sku_code="SKU-LEMON", brand_name="Lemon Fizz", supply_form="CARTRIDGE",
            case_pack_units=3, ounces_per_unit=1000, national_allocation_units=100,
        )
        add_telemetry(unit["id"], cola["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
        add_telemetry(unit["id"], lemon["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
        low = create_position(outlet["id"], cola["id"], 4)
        critical = create_position(outlet["id"], lemon["id"], 1)
        low_forecast = run_forecast(low["id"], "TRAILING_ACTUAL", 7)
        critical_forecast = run_forecast(critical["id"], "TRAILING_ACTUAL", 7)
        assert (low_forecast["alert_level"], low_forecast["requested_units"]) == ("LOW", 10)
        assert (critical_forecast["alert_level"], critical_forecast["requested_units"]) == (
            "CRITICAL", 13,
        )
        route, stop = _route_with_one_stop(outlet["id"], capacity_units=15)

        summary = allocate(stop["id"], [low["id"], critical["id"]])
        assert summary["total_allocated_units"] == 15
        assert summary["allocated_position_count"] == 2

        assert read_position(critical["id"])["allocated_units"] == 12
        assert read_position(low["id"])["allocated_units"] == 3
        assert read_supply_item(lemon["id"])["reserved_pool_units"] == 12
        assert read_supply_item(cola["id"])["reserved_pool_units"] == 3
        assert read_route(route["id"])["committed_units"] == 15


class TestHardStops:
    def test_a_pool_too_thin_for_one_case_aborts_the_whole_request(self, api):
        """PRD §3.7: "Before any grant is written for the position, two hard stops are
        checked in this order: if the unreserved pool is smaller than one
        `case_pack_units` the whole request is refused with
        `ERR_ALLOCATION_POOL_EXHAUSTED`, and if the remaining route capacity is smaller
        than one `case_pack_units` the whole request is refused with
        `ERR_ROUTE_CAPACITY_EXCEEDED`. Either refusal aborts the entire request and
        leaves no grant from it persisted."

        Design: Corner/calculations/allocation_pool_exhausted_rejects_the_whole_request
        """
        outlet, unit = _outlet_and_unit()
        item, position, forecast = _forecast_position(
            outlet, unit, 1, case_pack_units=3, national_allocation_units=2
        )
        assert forecast["alert_level"] == "CRITICAL"
        assert forecast["requested_units"] == 13
        route, stop = _route_with_one_stop(outlet["id"])

        validate_error(
            api.allocate_stop(
                stop["id"], allocation_payload([position["id"]]), PLANNER
            ),
            ApiErrorId.ERR_ALLOCATION_POOL_EXHAUSTED,
            409,
        )

        untouched = read_position(position["id"])
        assert untouched["allocated_units"] == 0
        assert untouched["planned_route_stop_id"] is None
        assert read_supply_item(item["id"])["reserved_pool_units"] == 0
        assert read_route(route["id"])["committed_units"] == 0

    def test_a_van_too_full_for_one_case_aborts_the_whole_request(self, api):
        """PRD §3.7: "Before any grant is written for the position, two hard stops are
        checked in this order: if the unreserved pool is smaller than one
        `case_pack_units` the whole request is refused with
        `ERR_ALLOCATION_POOL_EXHAUSTED`, and if the remaining route capacity is smaller
        than one `case_pack_units` the whole request is refused with
        `ERR_ROUTE_CAPACITY_EXCEEDED`. Either refusal aborts the entire request and
        leaves no grant from it persisted."

        Design: Corner/calculations/allocation_route_capacity_exceeded_rejects_the_whole_request
        """
        outlet, unit = _outlet_and_unit()
        item, position, forecast = _forecast_position(
            outlet, unit, 1, case_pack_units=3
        )
        assert forecast["alert_level"] == "CRITICAL"
        route, stop = _route_with_one_stop(outlet["id"], capacity_units=2)

        validate_error(
            api.allocate_stop(
                stop["id"], allocation_payload([position["id"]]), PLANNER
            ),
            ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED,
            409,
        )

        assert read_supply_item(item["id"])["reserved_pool_units"] == 0
        assert read_route(route["id"])["committed_units"] == 0


class TestEligibilityFilter:
    def test_a_position_with_no_alert_is_not_a_candidate_at_all(self, api):
        """PRD §3.7: "The submitted positions are first filtered for eligibility: a
        position qualifies only if its `outlet_id` is the stop's own outlet, its
        `alert_level` is `LOW` or `CRITICAL`, its `planned_route_stop_id` is currently
        null, its `promo_suppressed` flag is false, and its `requested_units` is at least
        1." An empty candidate set is an error: "If nothing survives the filter, the
        whole request is refused with `ERR_NO_ELIGIBLE_POSITIONS`."

        Design: Corner/calculations/allocation_skips_position_whose_alert_level_is_none
        """
        outlet, unit = _outlet_and_unit()
        _item, position, forecast = _forecast_position(outlet, unit, 7)
        assert forecast["alert_level"] == "NONE"
        assert forecast["requested_units"] == 7
        route, stop = _route_with_one_stop(outlet["id"])

        validate_error(
            api.allocate_stop(
                stop["id"], allocation_payload([position["id"]]), PLANNER
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_POSITIONS,
            422,
        )

        assert read_position(position["id"])["allocated_units"] == 0
        assert read_route(route["id"])["committed_units"] == 0

    def test_a_position_already_promised_to_one_stop_cannot_be_promised_twice(self, api):
        """PRD §3.7: "The submitted positions are first filtered for eligibility: a
        position qualifies only if its `outlet_id` is the stop's own outlet, its
        `alert_level` is `LOW` or `CRITICAL`, its `planned_route_stop_id` is currently
        null, its `promo_suppressed` flag is false, and its `requested_units` is at least
        1." An empty candidate set is an error: "If nothing survives the filter, the
        whole request is refused with `ERR_NO_ELIGIBLE_POSITIONS`."

        Design: Corner/calculations/allocation_skips_position_already_linked_to_another_stop
        """
        outlet, unit = _outlet_and_unit()
        _item, position, forecast = _forecast_position(outlet, unit, 2)
        assert forecast["requested_units"] == 12
        route, first = _route_with_one_stop(outlet["id"])
        second = add_stop(
            route["id"], outlet["id"], 2, "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"
        )
        allocate(first["id"], [position["id"]])

        validate_error(
            api.allocate_stop(
                second["id"], allocation_payload([position["id"]]), PLANNER
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_POSITIONS,
            422,
        )

        kept = read_position(position["id"])
        assert kept["allocated_units"] == 12
        assert kept["planned_route_stop_id"] == first["id"]
        assert read_route(route["id"])["committed_units"] == 12

    def test_a_suppressed_promotional_position_is_dropped_from_consideration(self, api):
        """PRD §3.7: "Positions that fail any of those tests — belonging to another
        outlet, already linked to a stop, promo-suppressed, sitting at `alert_level`
        `NONE`, or requesting nothing — are silently dropped from consideration rather
        than treated as errors. If nothing survives the filter, the whole request is
        refused with `ERR_NO_ELIGIBLE_POSITIONS`."

        Design: Corner/calculations/allocation_skips_promo_suppressed_position
        """
        outlet, unit = _outlet_and_unit()
        _item, position, forecast = _forecast_position(
            outlet, unit, 2,
            sku_code="SKU-PROMO",
            brand_name="Summer Splash",
            promotional=True,
            promo_window_start="2026-06-01T00:00:00Z",
            promo_window_end="2026-07-01T00:00:00Z",
        )
        assert forecast["promo_suppressed"] is True
        assert forecast["requested_units"] == 0
        assert forecast["alert_level"] == "CRITICAL"
        _route, stop = _route_with_one_stop(outlet["id"])

        validate_error(
            api.allocate_stop(
                stop["id"], allocation_payload([position["id"]]), PLANNER
            ),
            ApiErrorId.ERR_NO_ELIGIBLE_POSITIONS,
            422,
        )
