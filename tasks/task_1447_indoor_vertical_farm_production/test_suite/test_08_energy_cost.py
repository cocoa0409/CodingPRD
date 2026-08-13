"""Energy metering and cost per pound: dual variants, allocation shares, and
period partitioning (PRD §3.8, §2.6)."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_crop_with_active_recipe, create_loop_rack, create_growing_batch,
    mark_harvest_ready, harvest_batch, set_clock,
    create_energy_reading_payload,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]


class TestDualVariantCostPerPound:
    def _two_batch_metered_scenario(self, api):
        """B1: KALE 4 towers x 16h x 21d, harvested 46.00 lb on 2026-08-24.
        B2: BASIL 2 towers x 14h x 21d, still GROWING.
        One FACILITY reading [2026-08-03, 2026-08-24): 40000 kWh, peak 480 kW."""
        kale, _ = create_crop_with_active_recipe(crop_overrides={"crop_code": "KALE-01"})
        basil, _ = create_crop_with_active_recipe(
            crop_overrides={"crop_code": "BASIL-01", "display_name": "Basil", "category": "HERB",
                            "margin_cents_per_lb": 500, "floor_price_cents_per_lb": 200},
            recipe_overrides={"light_hours_per_day": 14, "expected_yield_lb_per_tower": 10.0})
        _, _, towers_a = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        _, _, towers_b = create_loop_rack(loop_code="WL-B", rack_code="R-02", tower_count=2)

        set_clock("2026-08-03T00:00:00Z")
        b1 = create_growing_batch(kale["id"], [t["id"] for t in towers_a],
                                  germination_rate_pct=96.0, seed_clock="2026-08-03T00:00:00Z")
        b2 = create_growing_batch(basil["id"], [t["id"] for t in towers_b],
                                  germination_rate_pct=100.0, seed_clock="2026-08-03T00:00:00Z")
        mark_harvest_ready(b1["id"], at_clock="2026-08-24T00:30:00Z")
        harvest_batch(b1["id"], 40.0, 6.0, 3.0, at_clock="2026-08-24T00:30:00Z")
        validate_success(api.create_energy_reading(create_energy_reading_payload(), FM),
                         expected_status=201)
        return b1, b2

    def test_provisional_and_actual_variants_diverge(self, api):
        """PRD §3.8: "The **provisional** variant is a nameplate projection available
        once a batch is seeded: the projected energy is the batch's tower count times
        the recipe's `light_hours_per_day` times `days_to_harvest` times the 0.6 kW
        fixture draw per tower; that energy times the facility rate of 11 cents per kWh
        gives the projected energy charge; dividing by `projected_yield_lb` and rounding
        half-up to two decimals yields the provisional cost per pound. It ignores
        metered reality and demand charges entirely." and the actual variant is "a
        genuinely different number from the provisional figure for identical batch
        inputs."

        Design: Difficulty/dual_variant_calc/energy_cost_provisional_vs_actual_per_pound
        """
        b1, _ = self._two_batch_metered_scenario(api)
        summary = validate_success(api.get_batch_cost_summary(b1["id"], FM))
        # 4 x 16 x 21 x 0.6 = 806.4 kWh x 11 = 8870.4 cents / 50.00 lb
        assert summary["provisional_cost_per_pound_cents"] == pytest.approx(177.41)
        # 606609 allocated cents / 46.00 harvested lb
        assert summary["actual_cost_per_pound_cents"] == pytest.approx(13187.15)
        assert summary["actual_cost_per_pound_cents"] != summary["provisional_cost_per_pound_cents"]

    def test_actual_variant_allocations_by_light_hour_share(self, api):
        """PRD §3.8: "The reading's energy charge is `kwh_consumed` times 11 cents per
        kWh, and its demand charge is tiered: the first 500 kW of `peak_demand_kw` price
        at 900 cents per kW, and any demand above 500 kW prices at 1400 cents per kW.
        Each charge is multiplied by the batch's share and rounded half-up to whole
        cents, producing the allocated `energy_alloc_cents` and `demand_alloc_cents`."

        Design: Difficulty/dual_variant_calc/energy_cost_provisional_vs_actual_per_pound
        """
        b1, _ = self._two_batch_metered_scenario(api)
        summary = validate_success(api.get_batch_cost_summary(b1["id"], FM))
        # shares: B1 4x16x21 = 1344 light-hours; B2 2x14x21 = 588; total 1932
        assert summary["energy_alloc_cents"] == 306087   # round_half_up(440000 x 1344/1932)
        assert summary["demand_alloc_cents"] == 300522   # round_half_up(432000 x 1344/1932)


class TestActualVariantAvailability:
    def test_cost_summary_null_actual_without_meter_reading(self, api):
        """PRD §3.8: "The **actual** variant engages only when a `FACILITY`-scope
        reading's period fully covers the batch's grow interval from `seeded_at` up to —
        but not including — `projected_harvest_at`; until such a reading exists, the
        batch's `actual_cost_per_pound_cents` is null."

        Design: Corner/endpoints/cost_summary_null_actual_without_meter_reading
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers],
                                     germination_rate_pct=96.0, seed_clock="2026-08-03T00:00:00Z")
        summary = validate_success(api.get_batch_cost_summary(batch["id"], GR))
        assert summary["provisional_cost_per_pound_cents"] == pytest.approx(177.41)
        assert summary["actual_cost_per_pound_cents"] is None
        assert summary["energy_alloc_cents"] is None
        assert summary["demand_alloc_cents"] is None

    def test_actual_basis_uses_projection_before_harvest(self, api):
        """PRD §3.8: "The per-pound basis is `harvested_total_lb` once the batch is
        `HARVESTED` or `PACKED`, and `projected_yield_lb` before that".

        Design: Corner/endpoints/energy_actual_basis_uses_projection_before_harvest
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers],
                                     germination_rate_pct=96.0, seed_clock="2026-08-03T00:00:00Z")
        validate_success(api.create_energy_reading(create_energy_reading_payload(), FM),
                         expected_status=201)
        summary = validate_success(api.get_batch_cost_summary(batch["id"], FM))
        # Sole intersecting batch: share 1 -> 440000 + 432000 = 872000 cents over
        # the 50.00 lb projection (batch still GROWING).
        assert summary["energy_alloc_cents"] == 440000
        assert summary["demand_alloc_cents"] == 432000
        assert summary["actual_cost_per_pound_cents"] == pytest.approx(17440.00)
        assert summary["provisional_cost_per_pound_cents"] == pytest.approx(177.41)


class TestEnergyPeriodPartitioning:
    def test_energy_period_overlap_partitioned_by_scope_key(self, api):
        """PRD §3.8: "Readings are partitioned by the combination of scope and zone, and
        within a partition no two periods may overlap — adjacency is fine, overlap is
        `ERR_ENERGY_PERIOD_OVERLAP`." PRD §2.6: "energy meter reading periods run from
        `period_start_at` (inclusive) to `period_end_at` (exclusive)".

        Design: Corner/calculations/energy_period_overlap_partitioned_by_scope_key
        """
        validate_success(api.create_energy_reading(create_energy_reading_payload(), FM),
                         expected_status=201)

        overlap = api.create_energy_reading(create_energy_reading_payload(
            period_start_at="2026-08-10T00:00:00Z", period_end_at="2026-08-31T00:00:00Z",
            kwh_consumed=100.0, peak_demand_kw=10.0), FM)
        validate_error(overlap, ApiErrorId.ERR_ENERGY_PERIOD_OVERLAP)

        adjacent = api.create_energy_reading(create_energy_reading_payload(
            period_start_at="2026-08-24T00:00:00Z", period_end_at="2026-09-07T00:00:00Z",
            kwh_consumed=100.0, peak_demand_kw=10.0), FM)
        validate_success(adjacent, expected_status=201)  # starts exactly at F1's end

        zone = api.create_energy_reading(create_energy_reading_payload(
            scope_type="ZONE", zone="Z1",
            period_start_at="2026-08-03T00:00:00Z", period_end_at="2026-08-24T00:00:00Z",
            kwh_consumed=50.0, peak_demand_kw=5.0), FM)
        validate_success(zone, expected_status=201)  # different partition key

        zone_overlap = api.create_energy_reading(create_energy_reading_payload(
            scope_type="ZONE", zone="Z1",
            period_start_at="2026-08-10T00:00:00Z", period_end_at="2026-08-12T00:00:00Z",
            kwh_consumed=5.0, peak_demand_kw=1.0), FM)
        validate_error(zone_overlap, ApiErrorId.ERR_ENERGY_PERIOD_OVERLAP)
