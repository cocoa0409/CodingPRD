"""Finished lots: dating, tiered cold-chain penalty, cooler capacity ledger,
shipping gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    assert_pct,
    create_finished_lot_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures

ADMIN = TEST_USERS["plant_admin_headers"]
PROD = TEST_USERS["production_manager_headers"]
QA = TEST_USERS["qa_manager_headers"]


def _drive_tiered_penalty(api, fl_id: str):
    """4h at 46F (x1.5) then 2h at 52F (x2.0): 6.0 + 4.0 = 10.0 penalty hours."""
    fixtures.set_clock("2026-08-02T00:00:00Z")
    fixtures.log_temperature(fl_id, 46.0)
    fixtures.set_clock("2026-08-02T04:00:00Z")
    fixtures.log_temperature(fl_id, 38.0)
    fixtures.set_clock("2026-08-03T00:00:00Z")
    fixtures.log_temperature(fl_id, 52.0)
    fixtures.set_clock("2026-08-03T02:00:00Z")
    return fixtures.log_temperature(fl_id, 39.0)


class TestShelfLifeTieredPenalty:
    def test_tiered_penalty_accumulates_per_interval(self, api):
        """PRD §3.8: "For every entry whose temperature is strictly above 40.0 °F, an interval is measured in hours — to the next entry's `recorded_at` when one exists, otherwise to the current logical clock — and that interval accrues into `penalty_hours` multiplied by a tier factor: 1.0 for readings above 40.0 °F and at most 45.0 °F, 1.5 for readings above 45.0 °F and at most 50.0 °F, and 2.0 for readings above 50.0 °F."
        PRD §3.8: "The recomputed `use_by_at` is the later of `production_date` and `base_use_by_at` minus `penalty_hours`; penalty hours are kept to two decimal places and timestamps are compared to the second."

        Design: Difficulty/combinatorial_formula/shelf_life_tiered_penalty_schedule
        """
        env, lot, label, fl = fixtures.setup_finished_lot(
            establishment_number="EST-1645-C1", shelf_life_days=10,
        )
        updated = _drive_tiered_penalty(api, fl["id"])
        assert_pct(updated["penalty_hours"], 10.0)
        # base 2026-08-11T07:00:00Z minus 10h -> 2026-08-10T21:00:00Z.
        assert_instant_equals(updated["use_by_at"], "2026-08-10T21:00:00Z")
        assert updated["status"] == "PRODUCED", (
            "use_by_at is still ahead of the 2026-08-03T02:00:00Z clock"
        )

    def test_dating_fields_established_at_creation(self, api):
        """PRD §3.8: "Dating is established from the logical clock: `production_date` is stamped now, `base_use_by_at` is set to `production_date` plus `shelf_life_days` times twenty-four hours, `penalty_hours` starts at zero, and `use_by_at` starts equal to `base_use_by_at`."

        Design: Difficulty/combinatorial_formula/shelf_life_tiered_penalty_schedule
        """
        env, lot, label, fl = fixtures.setup_finished_lot(
            establishment_number="EST-1645-C2", shelf_life_days=10,
        )
        # The environment clock was 2026-08-01T07:00:00Z at packing time.
        assert_instant_equals(fl["production_date"], "2026-08-01T07:00:00Z")
        assert_instant_equals(fl["base_use_by_at"], "2026-08-11T07:00:00Z")
        assert_pct(fl["penalty_hours"], 0.0)
        assert_instant_equals(fl["use_by_at"], "2026-08-11T07:00:00Z")

        updated = _drive_tiered_penalty(api, fl["id"])
        assert_instant_equals(updated["production_date"], "2026-08-01T07:00:00Z")
        assert_instant_equals(updated["base_use_by_at"], "2026-08-11T07:00:00Z")


class TestCoolerCapacityBoundary:
    def test_occupancy_equal_to_capacity_allowed_one_over_rejected(self, api):
        """PRD §3.1: "The creation gate rejects a packing run that would push occupancy strictly above capacity — landing exactly on capacity is allowed — with `ERR_COOLER_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/cooler_aggregate_capacity_boundary
        """
        env, lot, label, fl1 = fixtures.setup_finished_lot(
            establishment_number="EST-1645-P1", cooler_capacity_lbs=1000.0,
            units_produced=60, unit_weight_lbs=10.0,
        )
        assert_pct(fl1["total_weight_lbs"], 600.0)

        # 600.0 + 400.0 == 1000.0 == capacity: allowed (strictly-greater gate).
        fl2 = fixtures.pack_finished_lot(
            env["day"]["id"], lot["id"], label["id"],
            units_produced=40, unit_weight_lbs=10.0,
        )
        assert_pct(fl2["total_weight_lbs"], 400.0)

        # 1000.0 + 0.5 > 1000.0: rejected.
        blocked = api.create_finished_lot(
            env["day"]["id"],
            create_finished_lot_payload(
                source_lot_id=lot["id"], label_approval_id=label["id"],
                units_produced=1, unit_weight_lbs=0.5, shelf_life_days=10,
            ),
            PROD,
        )
        validate_error(blocked, ApiErrorId.ERR_COOLER_CAPACITY_EXCEEDED)
        assert blocked.status_code == 422

        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 1000.0)

    def test_rejected_packing_leaves_occupancy_unchanged(self, api):
        """PRD §3.1: "Cooler occupancy is a running ledger over the plant's finished lots: `cooler_occupied_lbs` is the sum of `total_weight_lbs` across the plant's finished lots in `PRODUCED`, `QUARANTINED`, or `SPOILED` status; lots that have been `SHIPPED` no longer occupy the cooler."

        Design: Difficulty/resource_temporal_overlap/cooler_aggregate_capacity_boundary
        """
        env, lot, label, fl1 = fixtures.setup_finished_lot(
            establishment_number="EST-1645-P2", cooler_capacity_lbs=1000.0,
            units_produced=60, unit_weight_lbs=10.0,
        )
        fixtures.pack_finished_lot(
            env["day"]["id"], lot["id"], label["id"],
            units_produced=40, unit_weight_lbs=10.0,
        )
        blocked = api.create_finished_lot(
            env["day"]["id"],
            create_finished_lot_payload(
                source_lot_id=lot["id"], label_approval_id=label["id"],
                units_produced=1, unit_weight_lbs=0.5, shelf_life_days=10,
            ),
            PROD,
        )
        validate_error(blocked, ApiErrorId.ERR_COOLER_CAPACITY_EXCEEDED)

        lots, meta = validate_paginated(
            api.list_finished_lots(QA, params={"production_day_id": env["day"]["id"]})
        )
        assert len(lots) == 2, "the rejected packing run must not persist a lot"
        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 1000.0)


class TestCoolerCreateShipConservation:
    def test_create_adds_and_ship_removes_exactly_total_weight(self, api):
        """PRD §3.1: "Packing a new finished lot adds exactly its `total_weight_lbs`, and shipping a lot removes exactly its `total_weight_lbs`, so occupancy always sits between zero and `cooler_capacity_lbs` inclusive."
        PRD §3.8: "A successful ship moves the lot to `SHIPPED`, stamps `shipped_at`, and credits `cooler_occupied_lbs` back by exactly the lot's `total_weight_lbs`."

        Design: Difficulty/compensating_invariant/cooler_occupancy_create_ship_conservation
        """
        env, lot, label, fl1 = fixtures.setup_finished_lot(
            establishment_number="EST-1645-R1",
            units_produced=100, unit_weight_lbs=10.0,
        )
        assert_pct(fl1["total_weight_lbs"], 1000.0)

        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 1000.0)

        shipped = validate_success(api.ship_finished_lot(fl1["id"], PROD), 200)
        assert shipped["status"] == "SHIPPED"
        assert shipped.get("shipped_at"), "ship stamps shipped_at"
        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 0.0)

        fixtures.pack_finished_lot(
            env["day"]["id"], lot["id"], label["id"],
            units_produced=50, unit_weight_lbs=10.0,
        )
        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 500.0)

    def test_quarantined_lot_still_occupies_cooler(self, api):
        """PRD §3.1: "Cooler occupancy is a running ledger over the plant's finished lots: `cooler_occupied_lbs` is the sum of `total_weight_lbs` across the plant's finished lots in `PRODUCED`, `QUARANTINED`, or `SPOILED` status; lots that have been `SHIPPED` no longer occupy the cooler."

        Design: Difficulty/compensating_invariant/cooler_occupancy_create_ship_conservation
        """
        env, lot, label, fl = fixtures.setup_finished_lot(
            establishment_number="EST-1645-R2",
            units_produced=50, unit_weight_lbs=10.0,
        )
        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 500.0)

        sample = fixtures.collect_sample(lot["id"])
        fixtures.report_sample(sample["id"], "POSITIVE")

        fl_after = validate_success(api.get_finished_lot(fl["id"], QA), 200)
        assert fl_after["status"] == "QUARANTINED"
        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 500.0,)


class TestFinishedLotCreateGateOrdering:
    def test_state_error_beats_safety_error(self, api):
        """PRD §3.8: "The gates run in a fixed order: the state family comes first — the owning day must be `OPEN` (`ERR_DAY_NOT_OPEN`) — followed by the business checks: the label must be `APPROVED` (`ERR_LABEL_INVALID_STATE`); no pathogen sample of the source lot may be `PENDING` or `POSITIVE` (`ERR_POSITIVE_PATHOGEN_UNRESOLVED`); the label must be the latest-approved application for its plant and `product_name`, meaning no other `APPROVED` label for the same product name exists whose approval executed later (`ERR_LABEL_VERSION_STALE`); and the cooler gate of §3.1 must admit the new weight (`ERR_COOLER_CAPACITY_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/finished_lot_create_state_error_beats_safety_error
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-I1"
        )
        label = fixtures.create_approved_label(env["plant"]["id"])
        fixtures.collect_sample(
            lot["id"], organism="ECOLI_O157H7", sample_type="GROUND_PRODUCT"
        )
        validate_success(api.suspend_production_day(env["day"]["id"], PROD), 200)

        resp = api.create_finished_lot(
            env["day"]["id"],
            create_finished_lot_payload(
                source_lot_id=lot["id"], label_approval_id=label["id"],
                units_produced=10, unit_weight_lbs=5.0, shelf_life_days=10,
            ),
            PROD,
        )
        # Both the state gate (day SUSPENDED) and the safety gate (PENDING
        # sample) fail; the state family is evaluated first.
        validate_error(resp, ApiErrorId.ERR_DAY_NOT_OPEN)
        assert resp.status_code == 409

        lots, meta = validate_paginated(
            api.list_finished_lots(QA, params={"production_day_id": env["day"]["id"]})
        )
        assert lots == [], "no finished lot is created"

    def test_safety_error_surfaces_once_state_gate_passes(self, api):
        """PRD §3.8: "The gates run in a fixed order: the state family comes first — the owning day must be `OPEN` (`ERR_DAY_NOT_OPEN`) — followed by the business checks: the label must be `APPROVED` (`ERR_LABEL_INVALID_STATE`); no pathogen sample of the source lot may be `PENDING` or `POSITIVE` (`ERR_POSITIVE_PATHOGEN_UNRESOLVED`); the label must be the latest-approved application for its plant and `product_name`, meaning no other `APPROVED` label for the same product name exists whose approval executed later (`ERR_LABEL_VERSION_STALE`); and the cooler gate of §3.1 must admit the new weight (`ERR_COOLER_CAPACITY_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/finished_lot_create_state_error_beats_safety_error
        """
        env, lot = fixtures.setup_fabricated_lot(
            establishment_number="EST-1645-I2"
        )
        label = fixtures.create_approved_label(env["plant"]["id"])
        fixtures.collect_sample(
            lot["id"], organism="ECOLI_O157H7", sample_type="GROUND_PRODUCT"
        )
        validate_success(api.suspend_production_day(env["day"]["id"], PROD), 200)
        validate_success(api.open_production_day(env["day"]["id"], PROD), 200)

        resp = api.create_finished_lot(
            env["day"]["id"],
            create_finished_lot_payload(
                source_lot_id=lot["id"], label_approval_id=label["id"],
                units_produced=10, unit_weight_lbs=5.0, shelf_life_days=10,
            ),
            PROD,
        )
        validate_error(resp, ApiErrorId.ERR_POSITIVE_PATHOGEN_UNRESOLVED)
        assert resp.status_code == 422


class TestShippingGates:
    def test_double_ship_returns_invalid_state_and_credits_once(self, api):
        """PRD §3.8: "A `ProductionManager` ships a lot in `PRODUCED` status; the temporal gate is inclusive — the logical clock must read at or before `use_by_at`, and a strictly-later clock rejects the shipment with `ERR_SHELF_LIFE_EXPIRED`."
        PRD §3.8: "A successful ship moves the lot to `SHIPPED`, stamps `shipped_at`, and credits `cooler_occupied_lbs` back by exactly the lot's `total_weight_lbs`."

        Design: Corner/state_machines/finished_lot_double_ship_returns_invalid_state
        """
        env, lot, label, fl = fixtures.setup_finished_lot(
            establishment_number="EST-1645-09",
            units_produced=50, unit_weight_lbs=10.0,
        )
        first = validate_success(api.ship_finished_lot(fl["id"], PROD), 200)
        assert first["status"] == "SHIPPED"

        again = api.ship_finished_lot(fl["id"], PROD)
        validate_error(again, ApiErrorId.ERR_FINISHED_LOT_INVALID_STATE)
        assert again.status_code == 409

        plant = validate_success(api.get_plant(env["plant"]["id"], ADMIN), 200)
        assert_pct(plant["cooler_occupied_lbs"], 0.0)

    def test_ship_after_use_by_returns_shelf_life_expired(self, api):
        """PRD §3.8: "A `ProductionManager` ships a lot in `PRODUCED` status; the temporal gate is inclusive — the logical clock must read at or before `use_by_at`, and a strictly-later clock rejects the shipment with `ERR_SHELF_LIFE_EXPIRED`."

        Design: Corner/validations/ship_after_use_by_returns_shelf_life_expired
        """
        env, lot, label, fl = fixtures.setup_finished_lot(
            establishment_number="EST-1645-29", shelf_life_days=1,
        )
        # production 2026-08-01T07:00:00Z + 1 day, no abuse on record.
        assert_instant_equals(fl["use_by_at"], "2026-08-02T07:00:00Z")

        fixtures.set_clock("2026-08-03T00:00:00Z")
        resp = api.ship_finished_lot(fl["id"], PROD)
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_EXPIRED)
        assert resp.status_code == 422

        after = validate_success(api.get_finished_lot(fl["id"], QA), 200)
        assert after["status"] == "PRODUCED"


class TestColdChainPenaltyEdge:
    def test_temperature_at_exactly_40_accrues_no_penalty(self, api):
        """PRD §3.8: "For every entry whose temperature is strictly above 40.0 °F, an interval is measured in hours — to the next entry's `recorded_at` when one exists, otherwise to the current logical clock — and that interval accrues into `penalty_hours` multiplied by a tier factor: 1.0 for readings above 40.0 °F and at most 45.0 °F, 1.5 for readings above 45.0 °F and at most 50.0 °F, and 2.0 for readings above 50.0 °F."
        PRD §3.8: "Entries at exactly 40.0 °F or below accrue nothing."

        Design: Corner/calculations/temperature_at_exactly_40_accrued_no_penalty
        """
        env, lot, label, fl = fixtures.setup_finished_lot(
            establishment_number="EST-1645-21", shelf_life_days=10,
        )
        fixtures.log_temperature(fl["id"], 40.0)
        fixtures.set_clock("2026-08-01T09:00:00Z")

        updated = fixtures.log_temperature(fl["id"], 39.0)
        assert_pct(updated["penalty_hours"], 0.0)
        assert_instant_equals(updated["base_use_by_at"], "2026-08-11T07:00:00Z")
        assert_instant_equals(updated["use_by_at"], "2026-08-11T07:00:00Z")
        assert updated["status"] == "PRODUCED"
