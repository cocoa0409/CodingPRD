"""GeoGrid CRUD, surge multiplier formula, heat-map snapshot."""
from __future__ import annotations

import pytest

from test_helpers import (
    AIRPORT_SURCHARGE,
    ApiErrorId,
    MULTIPLIER_CAP,
    assert_grid,
    assert_heatmap_snapshot_row,
    create_and_online_driver,
    create_driver,
    create_grid,
    create_grid_payload,
    create_requested_ride,
    create_rider,
    driver_go_online,
    expected_surge_multiplier,
    find_in_list,
    get_grid,
    list_heatmap,
    make_driver_headers,
    patch_grid_payload,
    setup_grid_with_demand_ratio,
    setup_grid_with_supply,
    sweep_recompute_surge,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create / Read / Patch.
# ===========================================================================
class TestGridCrud:

    def test_create_grid_returns_201(self, api, admin_headers):
        """PRD §4: "Operations that create a new, stand-alone resource
        (a grid, a driver, a rider, a rush-hour window, a quest, a ride,
        an airport-queue join row, or a dispute) return 201 Created."
        """
        resp = api.create_grid(create_grid_payload(), admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_grid(data)

    def test_create_grid_initial_counts_are_zero(self):
        """PRD §3.1: "The grid carries three derived numbers at all
        times: active_driver_count, the count of drivers in AVAILABLE
        status whose current_grid_code equals this grid's code;
        open_demand_count, the count of rides in REQUESTED status
        whose pickup_grid_code equals this grid's code."

        With no drivers and no rides, both must be 0.
        """
        grid = create_grid(is_airport=False, rush_hour_eligible=True)
        assert grid["active_driver_count"] == 0
        assert grid["open_demand_count"] == 0

    def test_create_grid_initial_multiplier_is_one(self):
        """PRD §2.5: "When the grid has neither an active_driver_count
        greater than zero nor any open_demand_count, the raw multiplier
        is 1.00." (then min(1.00, CAP) = 1.00)."""
        grid = create_grid(is_airport=False, rush_hour_eligible=True)
        assert grid["current_multiplier"] == 1.00

    def test_create_airport_grid_initial_multiplier_includes_surcharge(self):
        """PRD §2.5: "Step 2 — airport surcharge. If the grid's
        is_airport flag is true, the AIRPORT_SURCHARGE of 0.50 is added
        to the raw multiplier before any cap is applied."

        With no drivers and no rides → raw=1.00; +0.50 airport
        surcharge → 1.50; min(1.50, 3.00) = 1.50.
        """
        grid = create_grid(is_airport=True, rush_hour_eligible=True)
        assert grid["current_multiplier"] == 1.50

    def test_get_grid_returns_grid(self, api, admin_headers):
        """PRD §4: GET /grids/{id} reads a single GeoGrid."""
        grid = create_grid()
        resp = api.get_grid(grid["id"], admin_headers)
        data = validate_success(resp)
        assert data["id"] == grid["id"]
        assert_grid(data)

    def test_patch_grid_name_increments_version(self, api, admin_headers):
        """PRD §2.4: "version (integer): a system-managed monotonic
        counter that begins at 1 on creation and increments by 1 on
        every mutation." PRD §3.1: a patch may change name."""
        grid = create_grid()
        v0 = grid["version"]
        resp = api.patch_grid(
            grid["id"],
            patch_grid_payload(version=v0, name="Renamed"),
            admin_headers,
        )
        data = validate_success(resp)
        assert data["name"] == "Renamed"
        assert data["version"] == v0 + 1, (
            "PRD §2.4: version increments by 1 on every mutation."
        )

    def test_patch_grid_rush_hour_eligible_flag(self, api, admin_headers):
        """PRD §3.1: "only name and rush_hour_eligible may later be
        patched"."""
        grid = create_grid(rush_hour_eligible=True)
        resp = api.patch_grid(
            grid["id"],
            patch_grid_payload(version=grid["version"],
                               rush_hour_eligible=False),
            admin_headers,
        )
        data = validate_success(resp)
        assert data["rush_hour_eligible"] is False


# ===========================================================================
# Surge multiplier — PRD §2.5 boundary tests.
# ===========================================================================
class TestSurgeMultiplier:

    def test_one_driver_one_demand_yields_one(self):
        """PRD §2.5: "a ratio less than or equal to 1.0 yields a raw
        multiplier of 1.00".

        ratio = 1/1 = 1.0 → 1.00.
        """
        sc = setup_grid_with_demand_ratio(num_drivers=1, num_open_demand=1)
        grid = sc["grid"]
        assert grid["current_multiplier"] == 1.00

    def test_ratio_exactly_two_yields_one_point_five(self):
        """PRD §2.5: "a ratio less than or equal to 1.0 yields a raw
        multiplier of 1.00; greater than 1.0 and less than or equal to
        2.0 yields 1.50".

        ratio = 2/1 = 2.0 (the inclusive boundary of the 1.50 tier).
        # difficulty: boundary_precision_check/surge_ratio_exact_threshold_2_0
        """
        sc = setup_grid_with_demand_ratio(num_drivers=1, num_open_demand=2)
        grid = sc["grid"]
        assert grid["current_multiplier"] == 1.50, (
            f"PRD §2.5: ratio=2.0 is the inclusive boundary of the 1.50 "
            f"tier ('<= 2.0'), so current_multiplier must be 1.50, not "
            f"2.00. Got {grid['current_multiplier']}."
        )

    def test_ratio_just_above_two_yields_two(self):
        """PRD §2.5: "greater than 2.0 and less than or equal to 3.0
        yields 2.00".

        ratio = 3/1 = 3.0 → 2.00 (also at the inclusive boundary).
        """
        sc = setup_grid_with_demand_ratio(num_drivers=1, num_open_demand=3)
        grid = sc["grid"]
        assert grid["current_multiplier"] == 2.00

    def test_ratio_above_four_saturates_at_cap(self):
        """PRD §2.5: "strictly greater than 4.0 yields the
        MULTIPLIER_CAP of 3.00."

        ratio = 5/1 = 5.0 > 4.0 → MULTIPLIER_CAP=3.00.
        """
        sc = setup_grid_with_demand_ratio(num_drivers=1, num_open_demand=5)
        grid = sc["grid"]
        assert grid["current_multiplier"] == MULTIPLIER_CAP

    def test_zero_supply_zero_demand_is_one(self):
        """PRD §2.5: "When the grid has neither an active_driver_count
        greater than zero nor any open_demand_count, the raw multiplier
        is 1.00."
        """
        grid = create_grid(is_airport=False, rush_hour_eligible=False)
        assert grid["current_multiplier"] == 1.00

    def test_zero_supply_positive_demand_saturates_at_cap(self):
        """PRD §2.5: "When active_driver_count is zero but
        open_demand_count is positive, the raw multiplier saturates to
        the MULTIPLIER_CAP of 3.00 (the infinite-demand boundary)."
        """
        grid = create_grid(is_airport=False, rush_hour_eligible=False)
        rider = create_rider()
        # Create one ride against this grid; no drivers online → supply=0,
        # demand=1, no available driver. The ride still creates (PRD §3.3
        # doesn't require a driver) and demand becomes 1.
        create_requested_ride(rider["id"], grid["code"])
        grid_after = get_grid(grid["id"])
        assert grid_after["current_multiplier"] == MULTIPLIER_CAP

    def test_airport_surcharge_under_cap(self):
        """PRD §2.5 Step 2: "If the grid's is_airport flag is true, the
        AIRPORT_SURCHARGE of 0.50 is added to the raw multiplier before
        any cap is applied."

        ratio = 1/1 = 1.00, +0.50 surcharge → 1.50, min(1.50, 3.00) = 1.50.
        """
        sc = setup_grid_with_demand_ratio(
            num_drivers=1, num_open_demand=1, is_airport=True,
        )
        grid = sc["grid"]
        # PRD §2.5: "drivers in the airport queue do not contribute to
        # active_driver_count". Here the driver is AVAILABLE not queued,
        # so contributes.
        assert grid["current_multiplier"] == 1.50

    def test_airport_surcharge_cap_precedence(self):
        """PRD §2.5: "Step 3 — apply cap. The grid's current_multiplier
        is the minimum of the post-surcharge raw value and the
        MULTIPLIER_CAP of 3.00".

        ratio=5/1=5.0 > 4.0 → raw=3.00; +0.50 airport surcharge
        attempted; cap clamps result to 3.00.
        # difficulty: combinatorial_formula/surge_tiered_threshold_with_airport_then_cap
        """
        sc = setup_grid_with_demand_ratio(
            num_drivers=1, num_open_demand=5, is_airport=True,
        )
        grid = sc["grid"]
        assert grid["current_multiplier"] == MULTIPLIER_CAP, (
            f"PRD §2.5: airport surcharge cannot push final multiplier "
            f"above MULTIPLIER_CAP=3.00. Got {grid['current_multiplier']}."
        )

    def test_multiplier_stored_to_two_decimal_places(self):
        """PRD §2.5: "rounded half-up to two decimal places".
        PRD §2.6: "All multiplier arithmetic carries two decimal places
        of precision and likewise uses round half-up. The
        current_multiplier written on a GeoGrid is stored to exactly
        two decimal places."
        """
        sc = setup_grid_with_demand_ratio(num_drivers=2, num_open_demand=3)
        grid = sc["grid"]
        m = grid["current_multiplier"]
        # Two-decimal: m * 100 must be an integer when serialized.
        assert abs(round(m * 100) - m * 100) < 1e-9, (
            f"PRD §2.5: current_multiplier stored to exactly two decimal "
            f"places, got {m}."
        )


# ===========================================================================
# Surge recomputation triggers — PRD §2.5, §3.2.
# ===========================================================================
class TestSurgeRecomputeTriggers:

    def test_driver_go_online_recomputes_multiplier(self):
        """PRD §2.5: "It is recomputed any time the grid's supply or
        demand state shifts — that is, on any event that changes its
        active_driver_count or its open_demand_count."

        Going online increments active_driver_count by 1 (PRD §3.2:
        "the destination grid's active_driver_count is incremented by
        1, and triggers a fresh surge recomputation on that grid").
        """
        grid = create_grid()
        assert grid["active_driver_count"] == 0
        create_and_online_driver(grid["code"])
        grid_after = get_grid(grid["id"])
        assert grid_after["active_driver_count"] == 1

    def test_driver_go_offline_decrements_active_driver_count(self):
        """PRD §3.2: "Going offline reverses these effects: from
        AVAILABLE, the driver returns to OFFLINE, the grid's
        active_driver_count is decremented by 1, the grid's multiplier
        is recomputed, and current_grid_code is set to null."
        """
        from test_helpers import driver_go_offline
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        assert grid["active_driver_count"] == 1
        driver_go_offline(drivers[0]["id"])
        grid_after = get_grid(grid["id"])
        assert grid_after["active_driver_count"] == 0

    def test_request_ride_increments_open_demand_count(self):
        """PRD §3.3: "After creation, the grid's open_demand_count is
        incremented by one and its surge is recomputed."
        """
        grid, drivers = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        create_requested_ride(rider["id"], grid["code"])
        grid_after = get_grid(grid["id"])
        assert grid_after["open_demand_count"] == 1


# ===========================================================================
# Heat-map view + sweep snapshot.
# ===========================================================================
class TestHeatMapAndSweep:

    def test_sweep_writes_heatmap_snapshot_per_grid(self, api,
                                                    admin_headers):
        """PRD §3.1: "A snapshot batch is produced by the admin-only
        test-driving sweep capability, which forces a fresh surge
        recomputation for all grids and then writes one snapshot row
        per grid recording the grid's code (under grid_code), its
        post-recomputation multiplier, its active_driver_count, and its
        open_demand_count."
        """
        grid1 = create_grid()
        grid2 = create_grid()
        snapshots = sweep_recompute_surge()
        codes = {row["grid_code"] for row in snapshots}
        assert grid1["code"] in codes, (
            "PRD §3.1: sweep writes one snapshot row per grid."
        )
        assert grid2["code"] in codes
        for row in snapshots:
            if row["grid_code"] in (grid1["code"], grid2["code"]):
                assert_heatmap_snapshot_row(row)

    def test_heatmap_returns_latest_snapshot_per_grid(self):
        """PRD §3.1: "It returns, for each grid, the most recent
        HeatMapSnapshot row (descending by snapshot_at)."
        """
        grid = create_grid()
        # First sweep.
        sweep_recompute_surge()
        # Second sweep — should generate a newer snapshot for the grid.
        snapshots2 = sweep_recompute_surge()
        first_snap = find_in_list(snapshots2, grid_code=grid["code"])
        heatmap = list_heatmap()
        # The latest row for this grid_code must equal the latest sweep.
        latest_for_grid = find_in_list(heatmap, grid_code=grid["code"])
        assert latest_for_grid is not None
        # The snapshot_at must match the most recent sweep (which is the
        # second sweep, snapshots2).
        assert latest_for_grid["snapshot_at"] == first_snap["snapshot_at"], (
            "PRD §3.1: heat map returns the most recent snapshot per "
            "grid_code."
        )
