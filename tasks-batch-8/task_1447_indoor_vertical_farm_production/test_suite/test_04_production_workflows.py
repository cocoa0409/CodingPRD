"""Production workflows: germination tiers, stress schedule, harvest cascades,
tower allocation windows, rack posture gates, and read-your-write consistency
(PRD §2.6, §2.8, §3.2, §3.3)."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, validate_instant_equal,
    create_crop_with_active_recipe, create_loop_rack, create_growing_batch,
    create_batch, seed_batch, mark_harvest_ready, harvest_batch,
    set_clock, schedule_cycle, start_cycle, record_cycle_result, safety_release,
    make_grower_headers,
    SEED_CLOCK, HARVEST_CLOCK, HARVESTER_USER_ID,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]


class TestYieldTierLadder:
    def _four_seeded_batches(self, api):
        crop, _ = create_crop_with_active_recipe()
        _, _, towers_a = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=8)
        _, _, towers_b = create_loop_rack(loop_code="WL-B", rack_code="R-02", tower_count=8)
        groups = [towers_a[0:4], towers_a[4:8], towers_b[0:4], towers_b[4:8]]
        batches = []
        set_clock(SEED_CLOCK)
        for group in groups:
            b = create_batch(crop["id"], [t["id"] for t in group])
            seed_batch(b["id"])
            batches.append(b)
        return batches

    def test_yield_tier_boundaries_belong_to_upper_tier(self, api):
        """PRD §3.3: "a rate of 95.0 or higher yields 1.00; at least 85.0 but below 95.0
        yields 0.90; at least 75.0 but below 85.0 yields 0.75; below 75.0 yields 0.50
        and simultaneously sets `replant_recommended` true. `projected_yield_lb` is then
        recomputed as the active-allocation tower count times
        `expected_yield_lb_per_tower` times the new `yield_factor`, rounded half-up to
        two decimals."

        Design: Corner/calculations/yield_tier_ladder_all_boundaries
        """
        b1, b2, b3, b4 = self._four_seeded_batches(api)
        r1 = validate_success(api.germination_check_batch(b1["id"], {"germination_rate_pct": 95.0}, GR))
        r2 = validate_success(api.germination_check_batch(b2["id"], {"germination_rate_pct": 94.9}, GR))
        r3 = validate_success(api.germination_check_batch(b3["id"], {"germination_rate_pct": 85.0}, GR))
        r4 = validate_success(api.germination_check_batch(b4["id"], {"germination_rate_pct": 84.9}, GR))

        assert r1["yield_factor"] == pytest.approx(1.00) and r1["projected_yield_lb"] == pytest.approx(50.00)
        assert r2["yield_factor"] == pytest.approx(0.90) and r2["projected_yield_lb"] == pytest.approx(45.00)
        # 85.0 belongs to the upper tier (>= 85.0 -> 0.90)
        assert r3["yield_factor"] == pytest.approx(0.90) and r3["projected_yield_lb"] == pytest.approx(45.00)
        assert r4["yield_factor"] == pytest.approx(0.75) and r4["projected_yield_lb"] == pytest.approx(37.50)

    def test_germination_75_stays_normal_tier(self, api):
        """PRD §3.3: "at least 75.0 but below 85.0 yields 0.75; below 75.0 yields 0.50
        and simultaneously sets `replant_recommended` true."

        Design: Difficulty/boundary_precision_check/germination_threshold_75_boundary
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], germination_rate_pct=75.0,
                                     seed_clock=SEED_CLOCK)
        # create_growing_batch already ran the check at 75.0
        assert batch["yield_factor"] == pytest.approx(0.75)
        assert batch["replant_recommended"] is False, "exactly 75.0 stays in the normal tier ladder"
        assert batch["projected_yield_lb"] == pytest.approx(37.50)
        assert batch["production_status"] == "GROWING"

    def test_germination_74_9_crosses_replant_cliff(self, api):
        """PRD §3.3: "below 75.0 yields 0.50 and simultaneously sets `replant_recommended`
        true."

        Design: Difficulty/boundary_precision_check/germination_threshold_75_boundary
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], germination_rate_pct=74.9,
                                     seed_clock=SEED_CLOCK)
        assert batch["yield_factor"] == pytest.approx(0.50)
        assert batch["replant_recommended"] is True
        assert batch["projected_yield_lb"] == pytest.approx(25.00)
        assert batch["production_status"] == "GROWING", "the replant flag is advisory, not a state block"


class TestStressSchedule:
    def test_stress_extension_cap_and_projection_shift(self, api):
        """PRD §3.3: "Reporting stress on a `GROWING` batch ... moves it to `AT_RISK`,
        adds one to `stress_extension_days`, pushes `projected_harvest_at` out by 24
        hours" and "The extension is cumulative but capped at five days; a report made
        with `stress_extension_days` already at five is rejected with
        `ERR_STRESS_CAP_REACHED`."

        Design: Corner/calculations/stress_extension_cap_and_projection_shift
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)

        for i in range(5):
            validate_success(api.report_stress_batch(batch["id"], {"stress_note": f"s{i+1}"}, GR))
            validate_success(api.recover_batch(batch["id"], GR))

        after5 = validate_success(api.get_batch(batch["id"], GR))
        assert after5["stress_extension_days"] == 5
        validate_instant_equal(after5["projected_harvest_at"], "2026-08-29T06:00:00Z")

        resp = api.report_stress_batch(batch["id"], {"stress_note": "s6"}, GR)
        validate_error(resp, ApiErrorId.ERR_STRESS_CAP_REACHED)
        after6 = validate_success(api.get_batch(batch["id"], GR))
        assert after6["stress_extension_days"] == 5
        validate_instant_equal(after6["projected_harvest_at"], "2026-08-29T06:00:00Z")


class TestParallelStatusDimensions:
    def test_stress_cycle_preserves_extension_through_recover(self, api):
        """PRD §3.3: "Reporting stress on a `GROWING` batch ... moves it to `AT_RISK`"
        and "A batch that weathers the stress can be recovered from `AT_RISK` back to
        `GROWING`, and the accumulated extension persists."

        Design: Difficulty/non_linear_state_machine/batch_parallel_production_safety_dimensions_with_stress_cycle
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)

        stressed = validate_success(api.report_stress_batch(batch["id"], {"stress_note": "EC drift"}, GR))
        assert stressed["production_status"] == "AT_RISK"
        assert stressed["stress_extension_days"] == 1
        recovered = validate_success(api.recover_batch(batch["id"], GR))
        assert recovered["production_status"] == "GROWING"
        assert recovered["stress_extension_days"] == 1, "extension persists through recover"

    def test_safety_dimension_independent_of_production_cycle(self, api):
        """PRD §3.3: "Throughout this lifecycle the batch's two status dimensions evolve
        independently: `production_status` walks the agronomy pipeline while
        `safety_status` ... tracks the food-safety decision". PRD §3.4: "Releasing is
        permitted while the batch's `production_status` is `GROWING`, `AT_RISK`,
        `HARVEST_READY`, `HARVESTED`, or `PACKED`".

        Design: Difficulty/non_linear_state_machine/batch_parallel_production_safety_dimensions_with_stress_cycle
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)

        validate_success(api.report_stress_batch(batch["id"], {"stress_note": "EC drift"}, GR))
        validate_success(api.recover_batch(batch["id"], GR))
        released = safety_release(batch["id"], lab_ref="LAB-31")
        assert released["safety_status"] == "RELEASED"
        assert released["production_status"] == "GROWING", "safety release must not disturb production"

        stressed2 = validate_success(api.report_stress_batch(batch["id"], {"stress_note": "pH spike"}, GR))
        assert stressed2["production_status"] == "AT_RISK"
        assert stressed2["safety_status"] == "RELEASED", "production stress must not reset safety"
        assert stressed2["stress_extension_days"] == 2
        validate_instant_equal(stressed2["projected_harvest_at"], "2026-08-26T06:00:00Z")


class TestHarvestReleaseCascade:
    def _ready_batch(self, api, tower_count=4):
        crop, _ = create_crop_with_active_recipe()
        loop, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=tower_count)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        mark_harvest_ready(batch["id"])
        return crop, rack, towers, batch

    def test_harvest_releases_allocations_and_towers(self, api):
        """PRD §3.3: "Harvest also fires the three-link release cascade of §2.8: every
        active allocation flips to `RELEASED`, each freed tower returns to `IDLE`".

        Design: Difficulty/transitive_cascade/harvest_three_link_release_cascade
        """
        _, _, towers, batch = self._ready_batch(api)
        validate_success(api.harvest_batch(
            batch["id"], {"grade_a_lb": 40.0, "grade_b_lb": 6.0, "cull_lb": 3.0},
            make_grower_headers(HARVESTER_USER_ID)))

        allocations, _ = validate_paginated(api.list_batch_allocations(batch["id"], GR))
        assert len(allocations) == 4
        assert all(a["allocation_status"] == "RELEASED" for a in allocations)
        for t in towers:
            tower = validate_success(api.get_tower(t["id"], FM))
            assert tower["tower_status"] == "IDLE"

    def test_harvest_decrements_rack_occupancy_and_records_totals(self, api):
        """PRD §3.3: "each affected rack's `occupied_towers` drops by the number of
        released towers" and "computes `harvested_total_lb` as the sum of the two grade
        pounds with cull pounds excluded". PRD §3.2: "`occupied_towers`, the live count
        of active tower allocations across its towers".

        Design: Difficulty/transitive_cascade/harvest_three_link_release_cascade
        """
        _, rack, _, batch = self._ready_batch(api)
        rack_before = validate_success(api.get_rack(rack["id"], FM))
        assert rack_before["occupied_towers"] == 4

        harvested = validate_success(api.harvest_batch(
            batch["id"], {"grade_a_lb": 40.0, "grade_b_lb": 6.0, "cull_lb": 3.0},
            make_grower_headers(HARVESTER_USER_ID)))
        assert harvested["production_status"] == "HARVESTED"
        assert harvested["harvested_total_lb"] == pytest.approx(46.00), "40.0 + 6.0; cull excluded"

        rack_after = validate_success(api.get_rack(rack["id"], FM))
        assert rack_after["occupied_towers"] == 0


class TestTowerOccupancyInvariant:
    def test_occupancy_conserved_under_allocate_and_harvest_release(self, api):
        """PRD §2.8: "Harvesting, failing, or culling a grow batch releases its tower
        allocations; releasing an allocation returns its tower to `IDLE` and decrements
        the owning rack's `occupied_towers` by one."

        Design: Difficulty/compensating_invariant/tower_occupancy_conserved_under_allocate_release
        """
        crop, _ = create_crop_with_active_recipe()
        _, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        rack0 = validate_success(api.get_rack(rack["id"], FM))
        assert rack0["occupied_towers"] == 0

        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        rack_mid = validate_success(api.get_rack(rack["id"], FM))
        assert rack_mid["occupied_towers"] == 4

        mark_harvest_ready(batch["id"])
        harvest_batch(batch["id"], 46.0)
        rack_end = validate_success(api.get_rack(rack["id"], FM))
        assert rack_end["occupied_towers"] == 0, "compensating release restores the baseline"
        tower_end = validate_success(api.get_tower(towers[0]["id"], FM))
        assert tower_end["tower_status"] == "IDLE"

    def test_occupancy_conserved_under_allocate_and_fail_release(self, api):
        """PRD §2.8: "Harvesting, failing, or culling a grow batch releases its tower
        allocations; releasing an allocation returns its tower to `IDLE` and decrements
        the owning rack's `occupied_towers` by one."

        Design: Difficulty/compensating_invariant/tower_occupancy_conserved_under_allocate_release
        """
        crop, _ = create_crop_with_active_recipe()
        _, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        rack_mid = validate_success(api.get_rack(rack["id"], FM))
        assert rack_mid["occupied_towers"] == 4

        validate_success(api.fail_batch(batch["id"], {"cause_category": "EQUIPMENT"}, GR))
        rack_end = validate_success(api.get_rack(rack["id"], FM))
        assert rack_end["occupied_towers"] == 0
        tower_end = validate_success(api.get_tower(towers[0]["id"], FM))
        assert tower_end["tower_status"] == "IDLE"


class TestTowerAllocationWindows:
    def test_tower_allocation_half_open_adjacency_accepted(self, api):
        """PRD §3.2: "Allocation intervals are half-open — a new batch may begin exactly
        when a prior one ends — and any genuine overlap with an existing active
        allocation is rejected with `ERR_TOWER_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tower_allocation_half_open_adjacency
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=3)
        t1 = towers[0]["id"]
        batch_a = create_batch(crop["id"], [t1], planned_seed_at="2026-08-03T06:00:00Z")
        assert batch_a["production_status"] == "PLANNED"

        # Batch B begins exactly when A's 21-day interval ends: adjacency is allowed.
        resp_b = api.create_batch(
            {"crop_id": crop["id"], "tower_ids": [t1], "planned_seed_at": "2026-08-24T06:00:00Z"}, GR)
        validate_success(resp_b, expected_status=201)

        allocations, meta = validate_paginated(api.list_tower_allocations(t1, FM))
        active = [a for a in allocations if a["allocation_status"] == "ACTIVE"]
        assert len(active) == 2, "adjacent allocations A and B both remain active"

    def test_tower_allocation_one_minute_overlap_rejected(self, api):
        """PRD §3.2: "any genuine overlap with an existing active allocation is rejected
        with `ERR_TOWER_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tower_allocation_half_open_adjacency
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=3)
        t1 = towers[0]["id"]
        create_batch(crop["id"], [t1], planned_seed_at="2026-08-03T06:00:00Z")

        # One minute before A's interval ends is a genuine overlap.
        resp_c = api.create_batch(
            {"crop_id": crop["id"], "tower_ids": [t1], "planned_seed_at": "2026-08-24T05:59:00Z"}, GR)
        validate_error(resp_c, ApiErrorId.ERR_TOWER_INTERVAL_OVERLAP)


class TestHarvestRackGate:
    def _batch_ready_under_sanitation_hold(self, api):
        """Batch GROWING; sanitation starts (racks -> SANITATION_HOLD); batch marked
        HARVEST_READY while the cycle is in progress."""
        crop, _ = create_crop_with_active_recipe()
        loop, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        cycle = schedule_cycle(loop["id"], "2026-08-21T08:00:00Z", "2026-08-21T10:00:00Z")
        start_cycle(cycle["id"], "2026-08-21T08:00:00Z")
        batch = mark_harvest_ready(batch["id"])  # no rack gate on mark-harvest-ready
        return crop, loop, rack, batch, cycle

    def test_harvest_rejected_when_rack_not_operating(self, api):
        """PRD §3.3: "The harvest itself, performed by a `Grower` on a `HARVEST_READY`
        batch whose towers all sit on `OPERATING` racks (`ERR_RACK_NOT_OPERATING`
        otherwise)".

        Design: Difficulty/cross_entity_state_dependency/harvest_requires_rack_operating
        """
        _, _, _, batch, _ = self._batch_ready_under_sanitation_hold(api)
        assert batch["production_status"] == "HARVEST_READY", \
            "mark-harvest-ready has no rack gate and succeeds during sanitation"

        resp = api.harvest_batch(batch["id"],
                                 {"grade_a_lb": 40.0, "grade_b_lb": 6.0, "cull_lb": 3.0},
                                 make_grower_headers(HARVESTER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_RACK_NOT_OPERATING)
        after = validate_success(api.get_batch(batch["id"], GR))
        assert after["production_status"] == "HARVEST_READY", "rejection leaves no partial side effects"

    def test_harvest_succeeds_after_rack_returns_to_operating(self, api):
        """PRD §3.3: "The harvest itself, performed by a `Grower` on a `HARVEST_READY`
        batch whose towers all sit on `OPERATING` racks". PRD §3.4: "A `PASSED` result
        returns the loop to `IN_SERVICE` ... restores the held racks to `OPERATING`".

        Design: Difficulty/cross_entity_state_dependency/harvest_requires_rack_operating
        """
        _, _, _, batch, cycle = self._batch_ready_under_sanitation_hold(api)
        record_cycle_result(cycle["id"], "PASSED", 0, "2026-08-22T07:00:00Z")
        harvested = harvest_batch(batch["id"], 40.0, 6.0, 3.0)
        assert harvested["production_status"] == "HARVESTED"


class TestHarvestReadyEarliness:
    def test_harvest_ready_not_due_boundary(self, api):
        """PRD §3.3: "a batch in `GROWING` or `AT_RISK` may be marked `HARVEST_READY`
        only once the clock has reached 48 hours — two full days — before
        `projected_harvest_at`; earlier attempts fail with `ERR_HARVEST_NOT_DUE`."

        Design: Corner/errors/harvest_ready_not_due_boundary
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        # projected_harvest_at == 2026-08-24T06:00:00Z; window opens 2026-08-22T06:00:00Z
        set_clock("2026-08-22T05:59:00Z")
        resp = api.mark_harvest_ready_batch(batch["id"], GR)
        validate_error(resp, ApiErrorId.ERR_HARVEST_NOT_DUE)

        set_clock("2026-08-22T06:00:00Z")
        ready = validate_success(api.mark_harvest_ready_batch(batch["id"], GR))
        assert ready["production_status"] == "HARVEST_READY"


class TestRackOutOfService:
    def test_rack_out_of_service_with_active_batches_rejected(self, api):
        """PRD §3.2: "A `FarmManager` may set a rack out of service only when no active
        tower allocation exists on any of its towers — otherwise
        `ERR_RACK_HAS_ACTIVE_BATCHES`".

        Design: Corner/errors/rack_out_of_service_with_active_batches_rejected
        """
        crop, _ = create_crop_with_active_recipe()
        _, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)

        resp = api.set_rack_out_of_service(rack["id"], FM)
        validate_error(resp, ApiErrorId.ERR_RACK_HAS_ACTIVE_BATCHES)

        validate_success(api.fail_batch(batch["id"], {"cause_category": "EQUIPMENT"}, GR))
        after = validate_success(api.set_rack_out_of_service(rack["id"], FM))
        assert after["rack_posture"] == "OUT_OF_SERVICE"


class TestImmediateConsistency:
    def test_harvest_mutation_visible_in_same_response_and_read(self, api):
        """PRD §2.8: "every link of a chain is mandatory — an operation is not complete
        until every downstream resource has been reconciled." PRD §3.3: "The server
        stamps `harvested_at` from the clock ... computes `harvested_total_lb` as the
        sum of the two grade pounds with cull pounds excluded".

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response_and_read
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        mark_harvest_ready(batch["id"])

        set_clock(HARVEST_CLOCK)
        posted = validate_success(api.harvest_batch(
            batch["id"], {"grade_a_lb": 40.0, "grade_b_lb": 6.0, "cull_lb": 3.0},
            make_grower_headers(HARVESTER_USER_ID)))
        assert posted["production_status"] == "HARVESTED"
        assert posted["harvested_total_lb"] == pytest.approx(46.00)
        validate_instant_equal(posted["harvested_at"], "2026-08-24T06:30:00Z")

        read = validate_success(api.get_batch(batch["id"], GR))
        assert read["production_status"] == posted["production_status"]
        assert read["harvested_total_lb"] == pytest.approx(posted["harvested_total_lb"])
        assert read["harvested_at"] == posted["harvested_at"]

        tower = validate_success(api.get_tower(towers[0]["id"], FM))
        assert tower["tower_status"] == "IDLE", "cascade is visible immediately"
