"""Freezer-zone day-aggregate pallet capacity and per-lot rounding (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    complete_run,
    create_booking,
    create_freezer_zone,
    create_product,
    create_released_batch,
    create_run,
    create_verified_changeover,
    get_lot_for_run,
    get_success_data,
    make_qa_manager_headers,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PM, PLANNER


def _complete_pint_run(api, line, tunnel, zone, batch_id, run_code,
                       actual_units, booking_window, expect_error=False):
    pint = _PINT
    run = create_run(pint["id"], line["id"], run_code=run_code,
                     planned_units=actual_units,
                     scheduled_start="2026-08-10T14:00:00Z")
    create_verified_changeover(line["id"], pint["id"])
    create_booking(tunnel["id"], run["id"], start_at=booking_window[0],
                   end_at=booking_window[1])
    get_success_data(api.assign_mix(run["id"], {"mix_batch_id": batch_id},
                                    PLANNER))
    start_run(run["id"])
    resp = complete_run(run["id"], actual_units, 60.0, zone["id"])
    if expect_error:
        return run, resp
    return run, validate_success(resp)


_PINT = None


class TestZonePalletRounding:
    def test_zone_pallet_occupancy_per_lot_ceil_then_sum(self, api):
        """PRD §3.7: "A lot's pallets is the ceiling of (units_available plus
        units_reserved) divided by the product's units_per_pallet — the
        ceiling is taken per lot, and zone occupancy sums those per-lot
        integers after rounding (never ceiling of summed units)."
        Two lots of 150 units at 100 units/pallet: ceil(150/100)=2 per lot,
        so occupancy is 2+2 = 4 (not ceil(300/100) = 3).

        Design: Difficulty/combinatorial_formula/zone_pallet_occupancy_per_lot_ceil_then_sum
        """
        global _PINT
        _PINT = create_product(
            sku_code="BULK-PINT", product_name="Vanilla Pint", format="BULK",
            fill_volume_ml_per_unit=473, target_overrun_pct=30,
            units_per_pallet=100, shelf_life_days=540)
        line = get_success_data(api.create_line(
            {"line_code": "L-B", "format": "BULK", "rate_units_per_hour": 8000},
            PM), 201)
        tunnel = get_success_data(api.create_tunnel(
            {"tunnel_code": "T-2", "max_units_per_hour": 20000}, PM), 201)
        zone = create_freezer_zone(zone_code="Z-R", pallet_capacity=10)
        batch = create_released_batch(_PINT["id"], batch_code="MB-P",
                                      litres=500)
        run1, _ = _complete_pint_run(
            api, line, tunnel, zone, batch["id"], "R-P1", 150,
            ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"))
        run2, completed = _complete_pint_run(
            api, line, tunnel, zone, batch["id"], "R-P2", 150,
            ("2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z"))
        assert completed["status"] == "COMPLETED"
        lot1 = get_lot_for_run(run1["id"])
        lot2 = get_lot_for_run(run2["id"])
        assert lot1["pallets"] == 2, "ceil(150/100) per lot"
        assert lot2["pallets"] == 2
        zone_after = get_success_data(api.get_freezer_zone(zone["id"], PM))
        # Per-lot ceil THEN sum: 2 + 2 == 4. The sum-then-ceil order would
        # give ceil(300/100) == 3, which is observably wrong.
        assert zone_after["occupied_pallets"] == 4


class TestZonePalletRoundingSecond:
    def test_zone_occupancy_sums_quarantined_lots_too(self, api):
        """PRD §3.7: "The zone's occupied_pallets is the sum, over every lot
        in the zone whose status is AVAILABLE or QUARANTINED and whose
        occupancy window covers the current logical day, of that lot's
        pallets." A quarantined lot still occupies its per-lot-ceiled
        pallets, so 150+150 units in two lots stays 4 pallets after one lot
        is quarantined — per-lot rounding persists through the state flip.

        Design: Difficulty/combinatorial_formula/zone_pallet_occupancy_per_lot_ceil_then_sum
        """
        global _PINT
        _PINT = create_product(
            sku_code="BULK-PINT", product_name="Vanilla Pint", format="BULK",
            fill_volume_ml_per_unit=473, target_overrun_pct=30,
            units_per_pallet=100, shelf_life_days=540)
        line = get_success_data(api.create_line(
            {"line_code": "L-B", "format": "BULK", "rate_units_per_hour": 8000},
            PM), 201)
        tunnel = get_success_data(api.create_tunnel(
            {"tunnel_code": "T-2", "max_units_per_hour": 20000}, PM), 201)
        zone = create_freezer_zone(zone_code="Z-R", pallet_capacity=10)
        batch = create_released_batch(_PINT["id"], batch_code="MB-P",
                                      litres=500)
        run1, _ = _complete_pint_run(
            api, line, tunnel, zone, batch["id"], "R-P1", 150,
            ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"))
        _complete_pint_run(api, line, tunnel, zone, batch["id"], "R-P2", 150,
                           ("2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z"))
        lot1 = get_lot_for_run(run1["id"])
        validate_success(api.quarantine_lot(
            lot1["id"], make_qa_manager_headers("qa_1")))
        zone_after = get_success_data(api.get_freezer_zone(zone["id"], PM))
        # 2 (quarantined lot 1) + 2 (available lot 2): per-lot ceil then sum.
        assert zone_after["occupied_pallets"] == 4

    def test_zone_capacity_rejection_leaves_no_lot(self, api):
        """PRD §3.5: completion "runs the freezer-zone day-aggregate
        capacity check (§3.7); a failure rejects with
        ERR_ZONE_CAPACITY_EXCEEDED (HTTP 422)" — the rejection is atomic:
        no lot is created for the rejected completion.

        Design: Difficulty/resource_temporal_overlap/zone_day_aggregate_capacity_overlap
        """
        global _PINT
        _PINT = create_product(
            sku_code="BULK-PINT", product_name="Vanilla Pint", format="BULK",
            fill_volume_ml_per_unit=473, target_overrun_pct=30,
            units_per_pallet=100, shelf_life_days=540)
        line = get_success_data(api.create_line(
            {"line_code": "L-B", "format": "BULK", "rate_units_per_hour": 8000},
            PM), 201)
        tunnel = get_success_data(api.create_tunnel(
            {"tunnel_code": "T-2", "max_units_per_hour": 20000}, PM), 201)
        zone = create_freezer_zone(zone_code="Z-C", pallet_capacity=5)
        batch = create_released_batch(_PINT["id"], batch_code="MB-C",
                                      litres=500)
        _complete_pint_run(api, line, tunnel, zone, batch["id"], "R-C1", 300,
                           ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"))
        run2, resp = _complete_pint_run(
            api, line, tunnel, zone, batch["id"], "R-C2", 250,
            ("2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z"),
            expect_error=True)
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)
        # Zone occupancy is unchanged: only the first lot's 3 pallets count.
        zone_after = get_success_data(api.get_freezer_zone(zone["id"], PM))
        assert zone_after["occupied_pallets"] == 3


class TestZoneCapacityRejection:
    def test_zone_day_aggregate_capacity_overlap(self, api):
        """PRD §3.7: "For each such day, the sum of pallets over existing
        lots in the zone with status AVAILABLE or QUARANTINED whose window
        covers d, plus the new lot's pallets, must be no greater than
        pallet_capacity." A failure at completion "rejects with
        ERR_ZONE_CAPACITY_EXCEEDED (HTTP 422)" (§3.5).

        3 existing pallets + ceil(250/100)=3 new = 6 > capacity 5.

        Design: Difficulty/resource_temporal_overlap/zone_day_aggregate_capacity_overlap
        """
        global _PINT
        _PINT = create_product(
            sku_code="BULK-PINT", product_name="Vanilla Pint", format="BULK",
            fill_volume_ml_per_unit=473, target_overrun_pct=30,
            units_per_pallet=100, shelf_life_days=540)
        line = get_success_data(api.create_line(
            {"line_code": "L-B", "format": "BULK", "rate_units_per_hour": 8000},
            PM), 201)
        tunnel = get_success_data(api.create_tunnel(
            {"tunnel_code": "T-2", "max_units_per_hour": 20000}, PM), 201)
        zone = create_freezer_zone(zone_code="Z-C", pallet_capacity=5)
        batch = create_released_batch(_PINT["id"], batch_code="MB-C",
                                      litres=500)
        _complete_pint_run(api, line, tunnel, zone, batch["id"], "R-C1", 300,
                           ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"))
        run2, resp = _complete_pint_run(
            api, line, tunnel, zone, batch["id"], "R-C2", 250,
            ("2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z"),
            expect_error=True)
        validate_error(resp, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)
        # Run stays IN_PRODUCTION; no lot is created for it.
        run_after = get_success_data(api.get_production_run(run2["id"], PM))
        assert run_after["status"] == "IN_PRODUCTION"
        lots, meta = validate_paginated(
            api.list_inventory_lots(PM, params={"run_id": run2["id"]}))
        assert meta["total_count"] == 0
        assert lots == []
