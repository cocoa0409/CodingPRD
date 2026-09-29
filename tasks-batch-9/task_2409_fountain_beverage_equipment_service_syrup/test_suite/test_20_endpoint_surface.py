"""The endpoint surface: a partial update, a read-back, two filtered lists, a
pure computed read, the clock, and a conditional action that becomes legal.

Each test drives one endpoint of the network API and checks the shape of what it
returns alongside what it did — or, for the computed read, did not — persist.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    add_stop,
    add_telemetry,
    allocate,
    complete_task,
    create_agreement,
    create_call,
    create_outlet,
    create_position,
    create_route,
    create_supply_item,
    create_task,
    create_unit,
    create_van_stock,
    dispatch_call,
    evaluate_task,
    pin_clock,
    place_service_hold,
    read_outlet,
    read_supply_item,
    read_task,
    read_unit,
    run_forecast,
    service_hold_payload,
    set_clock_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
TECH = TEST_USERS["technician_headers"]
OFFICER = TEST_USERS["officer_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet_agreement_and_unit(serial_number="SN-9001"):
    """Riverside Diner with one IN_SERVICE machine under an 8000-gallon agreement."""
    pin_clock(CLOCK)
    outlet = create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number=serial_number, installed_at="2025-11-01T00:00:00Z",
    )
    return outlet, agreement, unit


class TestPartialUpdate:
    def test_an_adjustment_rewrites_the_pool_and_the_promo_bounds_only(self, api):
        """PRD §3.6: "A `NetworkAdmin` may later adjust a SKU, submitting any of
        `national_allocation_units`, `promo_window_start` and `promo_window_end`. The
        adjustment increments the SKU's `version` by one." What registration set stands
        untouched: "Registration answers 201 with `reserved_pool_units` at 0 and
        `version` 1; `reserved_pool_units` is server-maintained, never below zero and
        never above `national_allocation_units`."

        Design: Corner/endpoints/supply_item_patch_raises_the_pool_and_moves_the_promo_window
        """
        pin_clock(CLOCK)
        item = create_supply_item(
            sku_code="SKU-PROMO", brand_name="Summer Splash", supply_form="CARTRIDGE",
            case_pack_units=6, ounces_per_unit=1200, promotional=True,
            promo_window_start="2026-06-01T00:00:00Z",
            promo_window_end="2026-07-01T00:00:00Z",
            national_allocation_units=40,
        )
        assert item["version"] == 1

        adjusted = validate_success(
            api.patch_supply_item(
                item["id"],
                {
                    "national_allocation_units": 90,
                    "promo_window_start": "2026-07-15T00:00:00Z",
                    "promo_window_end": "2026-09-01T00:00:00Z",
                },
                ADMIN,
            )
        )
        assert adjusted["national_allocation_units"] == 90
        assert adjusted["promo_window_start"] == "2026-07-15T00:00:00Z"
        assert adjusted["promo_window_end"] == "2026-09-01T00:00:00Z"
        assert adjusted["case_pack_units"] == 6
        assert adjusted["ounces_per_unit"] == 1200
        assert adjusted["reserved_pool_units"] == 0
        assert adjusted["version"] == 2
        assert read_supply_item(item["id"])["version"] == 2


class TestReadBack:
    def test_a_freshly_loaded_van_row_reads_back_with_its_ledger_seeded(self, api):
        """PRD §3.8: "Creation answers 201 recording `initial_units` equal to the units
        supplied — a fixed baseline that never changes again — with `reserved_units`,
        `consumed_units` and `restocked_units` all 0 and `version` 1; none of the four
        counters may ever go negative." The row is named by its van and its part: "The
        van side of this story is a **VanPartStock** row, created by a `NetworkAdmin` who
        names the `van_code`, the `part_sku` such as `PUMP_ASSY_12`, and the
        `on_van_units` first loaded."

        Design: Corner/endpoints/van_part_stock_read_back_returns_the_four_ledger_buckets
        """
        pin_clock(CLOCK)
        stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)

        fetched = validate_success(api.get_van_part_stock(stock["id"], TECH))
        assert fetched["van_code"] == "VAN-7"
        assert fetched["part_sku"] == "PUMP_ASSY_12"
        assert fetched["on_van_units"] == 5
        assert fetched["initial_units"] == 5
        assert fetched["reserved_units"] == 0
        assert fetched["consumed_units"] == 0
        assert fetched["restocked_units"] == 0
        assert fetched["version"] == 1


class TestFilteredListing:
    def test_two_filter_terms_narrow_the_call_list_together(self, api):
        """PRD §3.8: "Calls can be listed filtered by `dispenser_unit_id`, by
        `reserved_part_stock_id`, by `status` and by `severity`." The bands come from the
        score: "The `severity` band follows from the score with inclusive lower bounds: a
        score of 85 or more is `CRITICAL`, a score of 60 or more but under 85 is
        `URGENT`, and anything below 60 is `ROUTINE` — a score of exactly 85 is
        `CRITICAL` and a score of exactly 60 is `URGENT`." Per §2.5: "List responses
        carry `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the
        envelope, where `total_count` is the number of rows matching the filters before
        pagination is applied and `has_more` is true when rows remain beyond the returned
        page."

        Design: Corner/endpoints/service_call_listing_filters_by_status_and_severity_together
        """
        outlet, agreement, first_unit = _outlet_agreement_and_unit()
        second_unit = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9002", installed_at="2025-11-01T00:00:00Z",
        )
        third_unit = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9003", installed_at="2025-11-01T00:00:00Z",
        )
        leak = create_call(first_unit["id"], "LEAK", CLOCK)
        ice = create_call(second_unit["id"], "ICE_FAULT", CLOCK)
        no_pour = create_call(third_unit["id"], "NO_POUR", CLOCK)
        dispatch_call(
            no_pour["id"], "VAN-7",
            "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH,
        )

        routine_and_open, meta = validate_paginated(
            api.list_service_calls(
                ADMIN,
                {"status": "OPEN", "severity": "ROUTINE", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert {row["id"] for row in routine_and_open} == {leak["id"], ice["id"]}

        excluded = validate_success(api.get_service_call(no_pour["id"], ADMIN))
        assert excluded["severity"] == "URGENT"
        assert excluded["status"] == "DISPATCHED"

    def test_positions_can_be_found_from_the_stop_they_were_promised_to(self, api):
        """PRD §3.6: "Positions can be listed filtered by `outlet_id`, by
        `supply_item_id`, by `planned_route_stop_id` and by `alert_level`." The link is
        written by the waterfall, per §3.7: "A positive grant writes the position's
        `allocated_units` and points its `planned_route_stop_id` at this stop, and raises
        both the SKU's `reserved_pool_units` and the route's `committed_units` by the
        granted amount."

        Design: Corner/endpoints/supply_position_listing_by_planned_route_stop_id_resolves_the_link
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit()
        item = create_supply_item(
            sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="CARTRIDGE",
            case_pack_units=4, ounces_per_unit=1000, national_allocation_units=100,
        )
        add_telemetry(unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
        position = create_position(outlet["id"], item["id"], 2)
        run_forecast(position["id"], "TRAILING_ACTUAL", 7)
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        stop = add_stop(
            route["id"], outlet["id"], 1,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
        )
        allocate(stop["id"], [position["id"]])

        promised, meta = validate_paginated(
            api.list_supply_positions(
                PLANNER,
                {"planned_route_stop_id": stop["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert promised[0]["id"] == position["id"]
        assert promised[0]["allocated_units"] == 12
        assert promised[0]["planned_route_stop_id"] == stop["id"]


class TestComputedRead:
    def test_reading_the_report_twice_changes_nothing_behind_it(self, api):
        """PRD §3.9: "Available to a `NetworkAdmin`, a `SupplyPlanner` or the
        `OutletManager` of the outlet in question, this computed read mutates nothing and
        reports over a fixed half-open 30-day period that ends at the logical clock."
        Mutation would have shown, per §2.4: "When one request mutates several resources,
        each mutated resource independently advances its own `version` by one; the
        counters of untouched resources stand still."

        Design: Corner/endpoints/brand_mix_report_is_a_pure_computed_read
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit()
        item = create_supply_item(
            sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="CARTRIDGE",
            case_pack_units=4, ounces_per_unit=1000,
        )
        add_telemetry(unit["id"], item["id"], 400, "2026-07-20T00:00:00Z", window_days=7)
        version_before = read_outlet(outlet["id"])["version"]

        first = validate_success(api.get_brand_mix_report(outlet["id"], ADMIN))
        second = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))
        for report in (first, second):
            assert report["total_ounces"] == pytest.approx(400, abs=0.01)
            assert len(report["lines"]) == 1
            assert report["lines"][0]["brand_name"] == "Cola Classic"
            assert report["lines"][0]["share_pct"] == pytest.approx(100.0, abs=0.01)

        assert read_outlet(outlet["id"])["version"] == version_before
        assert read_supply_item(item["id"])["version"] == 1


class TestClock:
    def test_moving_the_clock_answers_the_new_instant_and_ages_the_task(self, api):
        """PRD §2.3: "An administrative test-driving capability moves the clock: the
        caller supplies the target instant as `to_iso8601` and the server responds with
        the new instant in a body of the shape `{ current_utc: datetime }`. Setting the
        clock mutates no entity — no task is re-evaluated, no forecast is refreshed, no
        route is skipped as a side effect. What changes is the answer that every
        subsequent due-evaluation, forecast run, allocation, dispatch, term closure and
        report gives." The later evaluation then reads §3.5: "Otherwise, if the logical
        clock is at or past the task's `due_at` plus a 72-hour grace band, the
        `breach_kind` becomes `DATE` and the task goes to `OVERDUE`."

        Design: Corner/endpoints/clock_endpoint_reports_the_new_instant_and_changes_later_evaluations
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit()
        task = create_task(unit["id"], "PREVENTIVE", "2026-08-05T00:00:00Z")
        evaluate_task(task["id"])
        assert read_task(task["id"])["status"] == "SCHEDULED"

        moved = validate_success(
            api.set_clock(set_clock_payload("2026-08-09T00:00:00Z"), OFFICER)
        )
        assert moved["current_utc"] == "2026-08-09T00:00:00Z"

        aged = evaluate_task(task["id"])
        assert aged["status"] == "OVERDUE"
        assert aged["breach_kind"] == "DATE"
        outlet_after = read_outlet(outlet["id"])
        assert outlet_after["overdue_task_count"] == 1
        assert outlet_after["service_posture"] == "RESTRICTED"


class TestConditionalAction:
    def test_clearing_the_sanitation_task_unblocks_the_same_release(self, api):
        """PRD §3.3: "`PLACE` moves the unit `IN_SERVICE → SERVICE_HOLD`; `RELEASE` moves
        it `SERVICE_HOLD → IN_SERVICE`, but is blocked while any maintenance task of that
        unit whose `task_type` is `SANITATION` sits in `OVERDUE`, in which case the
        release is refused with `ERR_SANITATION_OVERDUE`." Completion clears the count,
        per §3.5: "Completing a task that was in `OVERDUE` also lowers the outlet's
        `overdue_task_count` by one and recomputes `service_posture`, which is how an
        outlet works its way back from `FROZEN` to `RESTRICTED` and eventually to `OPEN`."

        Design: Corner/endpoints/service_hold_release_allowed_once_the_sanitation_task_is_completed
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit()
        task = create_task(unit["id"], "SANITATION", "2026-07-01T00:00:00Z")
        assert evaluate_task(task["id"])["status"] == "OVERDUE"
        place_service_hold(unit["id"], TECH)
        complete_task(task["id"], TECH)

        released = validate_success(
            api.unit_service_hold(unit["id"], service_hold_payload("RELEASE"), TECH)
        )
        assert released["status"] == "IN_SERVICE"

        assert read_task(task["id"])["status"] == "COMPLETED"
        settled = read_outlet(outlet["id"])
        assert settled["overdue_task_count"] == 0
        assert settled["service_posture"] == "OPEN"
        assert read_unit(unit["id"])["status"] == "IN_SERVICE"
