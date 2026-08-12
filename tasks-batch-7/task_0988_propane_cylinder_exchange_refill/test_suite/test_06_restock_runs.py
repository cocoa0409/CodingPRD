"""Restock logistics: forecasting, dispatch gates, route conflicts, supersede (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_driver,
    create_priced_site,
    create_restock_run,
    create_site,
    dispatch_run,
    get_site,
    get_site_version,
    make_driver_headers,
    register_customer_cylinder,
    register_fleet_cylinders,
    setup_dispatch_scenario,
    swap_completed,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]


class TestSuggestedQuantity:
    def test_restock_suggested_qty_pinned_evaluation_order(self, api):
        """PRD §3.6: "`planned_full_count` is the forecast-driven suggestion: count the site's completed exchanges whose `business_date` falls in the trailing fourteen-day half-open window — beginning fourteen days before the current date and ending the day before it — and divide by fourteen to obtain the average daily swap rate, kept as an exact rational; multiply that average by the number of whole days from the current date to `planned_date` (floored at zero when the run is planned for today) and round up to a whole cylinder for the forecast demand; subtract the forecast from the site's current `full_on_hand` to project stock at arrival, a projection that may go negative; and finally set the suggestion to the smaller of the cage's free space — `cage_capacity_cylinders` minus `full_on_hand` — and the larger of zero and `par_level_full` minus the projection."
        PRD §3.6: "`planned_empty_pickup_count` is simply the site's `empty_on_hand` snapshot."

        Design: Difficulty/combinatorial_formula/restock_suggested_qty_pinned_evaluation_order
        """
        driver = create_driver(name="Driver One")
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=8, fill="FULL", serial_prefix="FQ")
        customers = [register_customer_cylinder(fill="EMPTY") for _ in range(3)]
        advance_clock("2026-05-14T00:00:00Z")
        for c in customers:
            swap_completed(site["id"], CLERK1, returned_cylinder_id=c["id"])
        advance_clock("2026-05-15T00:00:00Z")
        # full_on_hand 5, empty_on_hand 3; 3 swaps in the trailing 14-day window.
        run = create_restock_run(site["id"], driver["id"], "2026-05-25")  # 10 days out
        # avg = 3/14; forecast = ceil(3/14 * 10) = 3; projected = 5 - 3 = 2;
        # suggested = min(20 - 5, max(0, 12 - 2)) = 10
        assert run["planned_full_count"] == 10
        assert run["planned_empty_pickup_count"] == 3

    def test_restock_suggested_qty_same_day_planned_date(self, api):
        """PRD §3.6: "multiply that average by the number of whole days from the current date to `planned_date` (floored at zero when the run is planned for today) and round up to a whole cylinder for the forecast demand"

        Design: Difficulty/combinatorial_formula/restock_suggested_qty_pinned_evaluation_order
        """
        driver = create_driver(name="Same Day Driver")
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=8, fill="FULL", serial_prefix="FS")
        customers = [register_customer_cylinder(fill="EMPTY") for _ in range(3)]
        advance_clock("2026-05-14T00:00:00Z")
        for c in customers:
            swap_completed(site["id"], CLERK1, returned_cylinder_id=c["id"])
        # Run planned for today: days_until = 0, so forecast = 0 regardless of history.
        run = create_restock_run(site["id"], driver["id"], "2026-05-14")
        # full_on_hand 5; suggested = min(20 - 5, max(0, 12 - 5)) = 7
        assert run["planned_full_count"] == 7
        assert run["planned_empty_pickup_count"] == 3


class TestDispatchGates:
    def test_restock_empty_route_rejected(self, api):
        """PRD §3.6: "the route must be non-empty — `planned_full_count` plus `planned_empty_pickup_count` greater than zero, else `ERR_EMPTY_ROUTE`."

        Design: Corner/calculations/restock_empty_route_rejected
        """
        # Site at par (12 full, no sales history): suggested = min(8, max(0, 12-12)) = 0.
        site, driver, run = setup_dispatch_scenario(site_full=12, depot_full=0)
        assert run["planned_full_count"] == 0
        assert run["planned_empty_pickup_count"] == 0
        res = api.dispatch_restock_run(run["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_EMPTY_ROUTE, expected_status=422)

    def test_depot_stock_low_rejected(self, api):
        """PRD §3.6: "Finally the depot must be able to fill the order: the depot pool — fleet-owned, `CERTIFIED`, `FULL` cylinders with `current_site_id` null and not in transit — must hold at least `planned_full_count` cylinders, else `ERR_DEPOT_STOCK_LOW`."

        Design: Corner/calculations/depot_stock_low_rejected
        """
        # 5 full at site, no sales: suggested = min(15, 12-5) = 7; depot pool is empty.
        site, driver, run = setup_dispatch_scenario(site_full=5, depot_full=0)
        assert run["planned_full_count"] == 7
        res = api.dispatch_restock_run(run["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_DEPOT_STOCK_LOW, expected_status=409)

    def test_payload_exact_max_allowed_over_rejected(self, api):
        """PRD §3.6: "The payload check uses fixed cage weights: each planned full cylinder weighs 37 pounds and each planned empty 17 pounds, and the planned payload — fulls times 37 plus empties times 17 — must not exceed the driver's `vehicle_max_payload_lbs`; equality is permitted, and any excess rejects with `ERR_DOT_PAYLOAD_EXCEEDED`."

        Design: Corner/calculations/payload_exact_max_allowed_over_rejected
        """
        # Both sites plan 9 fulls (3 on hand, par 12): payload 9 * 37 = 333 lbs.
        site_a, driver_a, run_a = setup_dispatch_scenario(
            site_full=3, depot_full=9, vehicle_max_payload_lbs=333)
        site_b, driver_b, run_b = setup_dispatch_scenario(
            site_full=3, depot_full=0, vehicle_max_payload_lbs=332)
        assert run_a["planned_full_count"] == 9
        assert run_b["planned_full_count"] == 9
        dispatched = dispatch_run(run_a["id"])  # 333 <= 333 allowed
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["assigned_cylinder_count"] == 9
        res = api.dispatch_restock_run(run_b["id"], ADMIN)  # 333 > 332 rejected
        validate_error(res, ApiErrorId.ERR_DOT_PAYLOAD_EXCEEDED, expected_status=409)

    def test_dispatch_expired_cert_safety_beats_route_conflict(self, api):
        """PRD §2.7: "Incoming requests are validated against a fixed, fourteen-stage evaluation order; the first stage that fails determines the rejection, and later stages are not consulted."
        PRD §2.7 (stage 9): "A leak-blocked site refuses new sales (`ERR_SALES_BLOCKED`), and dispatch refuses an expired driver medical card (`ERR_DRIVER_CERT_EXPIRED`) or an overloaded vehicle (`ERR_DOT_PAYLOAD_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_expired_cert_safety_beats_route_conflict
        """
        # Run A dispatched for 2026-05-18 while the driver's medical was valid.
        site_a, driver, run_a = setup_dispatch_scenario(
            site_full=3, depot_full=9, planned_date="2026-05-18")
        dispatch_run(run_a["id"])
        # The medical card is then shortened to 2026-05-17, before run B's planned date.
        validate_success(
            api.patch_driver(driver["id"], {"dot_medical_expires_on": "2026-05-17"}, ADMIN), 200)
        # Run B: same driver, same planned_date (would also be a route conflict at stage 11).
        site_b = create_site(name="Site B")
        register_fleet_cylinders(site_id=site_b["id"], count=3, fill="FULL", serial_prefix="FB")
        run_b = create_restock_run(site_b["id"], driver["id"], "2026-05-18")
        res = api.dispatch_restock_run(run_b["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_DRIVER_CERT_EXPIRED, expected_status=409)

    def test_dispatch_expired_cert_alone(self, api):
        """PRD §3.6: "the `planned_date` must be on or before the driver's `dot_medical_expires_on` (else `ERR_DRIVER_CERT_EXPIRED`)"

        Design: Difficulty/priority_pair_validation_conflict/dispatch_expired_cert_safety_beats_route_conflict
        """
        # Driver's medical expires before the planned date; no other run exists.
        site, driver, run = setup_dispatch_scenario(
            site_full=3, depot_full=9, dot_medical_expires_on="2026-05-17",
            planned_date="2026-05-18")
        res = api.dispatch_restock_run(run["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_DRIVER_CERT_EXPIRED, expected_status=409)


class TestRouteConflict:
    def test_driver_same_day_run_conflict(self, api):
        """PRD §3.6: "the driver must have no other run in `DISPATCHED` or `IN_PROGRESS` on the same `planned_date` (else `ERR_DRIVER_ROUTE_CONFLICT`)"

        Design: Difficulty/resource_temporal_overlap/driver_same_day_run_conflict
        """
        driver = create_driver(name="Conflict Driver")
        site_a = create_site(name="RC Site A")
        register_fleet_cylinders(site_id=site_a["id"], count=3, fill="FULL", serial_prefix="RA")
        site_b = create_site(name="RC Site B")
        register_fleet_cylinders(site_id=site_b["id"], count=3, fill="FULL", serial_prefix="RB")
        register_fleet_cylinders(count=10, fill="FULL", serial_prefix="RD")  # depot pool
        run_a = create_restock_run(site_a["id"], driver["id"], "2026-05-20")
        dispatch_run(run_a["id"])
        run_b = create_restock_run(site_b["id"], driver["id"], "2026-05-20")
        res = api.dispatch_restock_run(run_b["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_DRIVER_ROUTE_CONFLICT, expected_status=409)

    def test_driver_next_day_run_free(self, api):
        """PRD §3.6: "the driver must have no other run in `DISPATCHED` or `IN_PROGRESS` on the same `planned_date` (else `ERR_DRIVER_ROUTE_CONFLICT`)" — the conflict interval is the whole calendar day; the next day is free.

        Design: Difficulty/resource_temporal_overlap/driver_same_day_run_conflict
        """
        driver = create_driver(name="Next Day Driver")
        site_a = create_site(name="ND Site A")
        register_fleet_cylinders(site_id=site_a["id"], count=3, fill="FULL", serial_prefix="NA")
        site_c = create_site(name="ND Site C")
        register_fleet_cylinders(site_id=site_c["id"], count=11, fill="FULL", serial_prefix="NC")
        register_fleet_cylinders(count=10, fill="FULL", serial_prefix="ND")  # depot pool
        run_a = create_restock_run(site_a["id"], driver["id"], "2026-05-20")
        dispatch_run(run_a["id"])
        run_c = create_restock_run(site_c["id"], driver["id"], "2026-05-21")
        assert run_c["planned_full_count"] == 1, "min(20-11, max(0, 12-11)) = 1"
        dispatched = dispatch_run(run_c["id"])
        assert dispatched["status"] == "DISPATCHED"


class TestArriveAndSupersede:
    def test_arrive_on_wrong_date_rejected(self, api):
        """PRD §3.6: "marks arrival, which requires the current logical date to equal the `planned_date` (else `ERR_INVALID_STATE`) and moves the run from `DISPATCHED` to `IN_PROGRESS`."

        Design: Corner/state_machines/arrive_on_wrong_date_rejected
        """
        site, driver, run = setup_dispatch_scenario(
            site_full=3, depot_full=9, planned_date="2026-05-20")
        dispatch_run(run["id"])
        # Clock is still at the startup date 2026-05-01, not the planned date.
        res = api.arrive_restock_run(run["id"], make_driver_headers(driver["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_supersede_cancels_prior_draft_run(self, api):
        """PRD §3.6: "Creation also supersedes: any existing `DRAFT` run for the same site is auto-cancelled, so a site carries at most one draft plan at a time."

        Design: Corner/state_machines/supersede_cancels_prior_draft_run
        """
        driver = create_driver(name="Supersede Driver")
        site = create_site(name="Supersede Site")
        run1 = create_restock_run(site["id"], driver["id"], "2026-05-20")
        run2 = create_restock_run(site["id"], driver["id"], "2026-05-21")
        assert run2["status"] == "DRAFT"
        run1_after = validate_success(api.get_restock_run(run1["id"], ADMIN), 200)
        assert run1_after["status"] == "CANCELLED", "superseded by the newer draft"

    def test_occ_restock_run_create_stale_version(self, api):
        """PRD §2.6: "Three write operations are guarded by optimistic concurrency control against the host site's `version`: creating a restock run, creating a pricing policy, and patching a site's configuration or status."
        PRD §2.6: "If the value does not match the site's current `version` — because another accepted write has advanced the site since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_restock_run_create_stale_version
        """
        driver = create_driver(name="OCC Driver")
        site = create_site(name="OCC Run Site")
        stale_version = site["version"]  # 1
        create_restock_run(site["id"], driver["id"], "2026-05-20")  # bumps site to v2
        res = api.create_restock_run(
            {
                "site_id": site["id"],
                "driver_id": driver["id"],
                "planned_date": "2026-05-21",
                "expected_site_version": stale_version,
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
