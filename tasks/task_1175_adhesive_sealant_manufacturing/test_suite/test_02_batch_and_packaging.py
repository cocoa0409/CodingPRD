"""Batch booking, vessel/dry-room windows, packaging fill allocation, pot life."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_complete_run,
    create_batch,
    create_dry_room,
    create_formulation,
    create_mixed_batch,
    create_run,
    create_vessel,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _base_formulation_and_vessel(code, capacity_liters=100, **formulation_overrides):
    set_clock()
    formulation = create_formulation(code, activate=True, **formulation_overrides)
    vessel = create_vessel(f"V-{code}", capacity_liters=capacity_liters)
    return formulation, vessel


class TestBatchCreation:
    def test_batch_create_extra_computed_field_input_ignored(self, api, batch_operator_headers):
        """PRD §3.3: "The batch's `remaining_bulk_volume_ml` starts equal to `batch_volume_ml`, its `written_off_volume_ml` starts at 0, and its `mixed_at`, `pot_life_deadline` remain null until mix completion."

        Design: Corner/entities/batch_create_extra_computed_field_input_ignored
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-CI-1")
        payload = {
            "formulation_id": formulation["id"],
            "vessel_id": vessel["id"],
            "mix_start_at": "2026-05-01T08:00:00Z",
            "mix_end_at": "2026-05-01T09:00:00Z",
            "batch_volume_ml": 5000,
            "remaining_bulk_volume_ml": 1,
        }
        resp = api.create_batch(payload, batch_operator_headers)
        data = validate_success(resp, expected_status=201)
        assert data["remaining_bulk_volume_ml"] == 5000
        assert data["status"] == "MIXING"
        assert data["mixed_at"] is None
        assert data["pot_life_deadline"] is None

    def test_batch_creation_creates_production_lot_one_to_one(self, api, qa_manager_headers):
        """PRD §3.3: "Creation is atomic with the creation of the batch's 1:1 **ProductionLot**: the lot is born in `AWAITING_TEST` qa status with `hold_status` `CLEAR`, its `lot_number` assigned by the server as `LOT-` followed by a zero-padded six-digit creation sequence (for example `LOT-000001`), its `batch_id` pointing back to the batch, its `formulation_id` denormalized from the batch for FIFO queries, and its `production_lot_id` stored on the batch for the reverse lookup."

        Design: Corner/entities/batch_creation_creates_production_lot_one_to_one
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-1TO1")
        batch = create_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        lot_id = batch["production_lot_id"]
        assert lot_id

        data, meta = validate_paginated(
            api.list_production_lots(qa_manager_headers, params={"batch_id": batch["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == lot_id
        assert data[0]["qa_status"] == "AWAITING_TEST"
        assert data[0]["hold_status"] == "CLEAR"
        assert data[0]["lot_number"] == "LOT-000001"

    def test_immediate_consistency_batch_create_response(self, api, qa_manager_headers):
        """PRD §3.3: "Creation is atomic with the creation of the batch's 1:1 **ProductionLot**: the lot is born in `AWAITING_TEST` qa status with `hold_status` `CLEAR`, its `lot_number` assigned by the server as `LOT-` followed by a zero-padded six-digit creation sequence (for example `LOT-000001`), its `batch_id` pointing back to the batch, its `formulation_id` denormalized from the batch for FIFO queries, and its `production_lot_id` stored on the batch for the reverse lookup."

        Design: Corner/consistency_model/immediate_consistency_batch_create_response
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-IMM")
        resp = api.create_batch(
            {
                "formulation_id": formulation["id"],
                "vessel_id": vessel["id"],
                "mix_start_at": "2026-05-01T08:00:00Z",
                "mix_end_at": "2026-05-01T09:00:00Z",
                "batch_volume_ml": 5000,
            },
            TEST_USERS_BO,
        )
        data = validate_success(resp, expected_status=201)
        assert data["production_lot_id"]
        assert data["remaining_bulk_volume_ml"] == 5000
        assert data["written_off_volume_ml"] == 0
        assert data["version"] == 1

        lot = validate_success(api.get_production_lot(data["production_lot_id"], qa_manager_headers))
        assert lot["qa_status"] == "AWAITING_TEST"

    def test_batch_create_with_draft_formulation_returns_409(self, api, batch_operator_headers):
        """PRD §3.3: "A `BatchOperator` opens production by creating a **ProductionBatch** in a payload containing the `formulation_id` (which must resolve to an `EFFECTIVE` formulation — otherwise `ERR_FORMULATION_NOT_EFFECTIVE`), the `vessel_id`, the planned mix window as `mix_start_at` and `mix_end_at`, and the total `batch_volume_ml` in millilitres."

        Design: Corner/errors/batch_create_with_draft_formulation_returns_409
        """
        set_clock()
        formulation = create_formulation("EPX-DRF", activate=False, pot_life_minutes=120)
        vessel = create_vessel("V-DRF", capacity_liters=100)
        resp = api.create_batch(
            {
                "formulation_id": formulation["id"],
                "vessel_id": vessel["id"],
                "mix_start_at": "2026-05-01T08:00:00Z",
                "mix_end_at": "2026-05-01T09:00:00Z",
                "batch_volume_ml": 1000,
            },
            batch_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORMULATION_NOT_EFFECTIVE)

    def test_vessel_capacity_exceeded_returns_422(self, api, batch_operator_headers):
        """PRD §3.3: "Independently, `batch_volume_ml` must not exceed the vessel's capacity expressed in millilitres (its `capacity_liters` multiplied by 1000); exceeding it is rejected with `ERR_VESSEL_CAPACITY_EXCEEDED`."

        Design: Corner/errors/vessel_capacity_exceeded_returns_422
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-CAP", capacity_liters=1, pot_life_minutes=120)
        resp = api.create_batch(
            {
                "formulation_id": formulation["id"],
                "vessel_id": vessel["id"],
                "mix_start_at": "2026-05-01T08:00:00Z",
                "mix_end_at": "2026-05-01T09:00:00Z",
                "batch_volume_ml": 2000,
            },
            batch_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VESSEL_CAPACITY_EXCEEDED)


class TestMixLifecycle:
    def test_complete_mix_twice_rejected(self, api, batch_operator_headers, plant_manager_headers):
        """PRD §3.3: "Complete-mix requires the batch still be in `MIXING`; because the clock sweep expires overdue `MIXING` batches the moment the clock passes `mix_end_at`, a late completion observes an `EXPIRED` batch and fails with `ERR_BATCH_INVALID_STATE`."

        Design: Corner/state_machines/complete_mix_twice_rejected
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-IDEM", pot_life_minutes=120)
        batch = create_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        first = validate_success(api.complete_mix(batch["id"], batch_operator_headers))
        assert first["status"] == "MIXED"
        mixed_at = first["mixed_at"]

        resp = api.complete_mix(batch["id"], batch_operator_headers)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)

        after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert after["status"] == "MIXED"
        assert after["mixed_at"] == mixed_at

    def test_mixing_batch_expiry_sweep_on_clock_advance(self, api, batch_operator_headers, plant_manager_headers, qa_manager_headers):
        """PRD §2.6: "Advancing the clock triggers one specific sweep: every `ProductionBatch` still in `MIXING` whose `mix_end_at` now lies strictly before the current clock reading is transitioned to `EXPIRED`, and each such batch's `ProductionLot` — if its `qa_status` is still `AWAITING_TEST`, `TESTING`, or `UNDER_REVIEW` — is moved to `REJECTED`."
        PRD §3.3: "Complete-mix requires the batch still be in `MIXING`; because the clock sweep expires overdue `MIXING` batches the moment the clock passes `mix_end_at`, a late completion observes an `EXPIRED` batch and fails with `ERR_BATCH_INVALID_STATE`."

        Design: Corner/state_machines/mixing_batch_expiry_sweep_on_clock_advance
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-SWP", pot_life_minutes=120)
        batch = create_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        lot_id = batch["production_lot_id"]

        set_clock("2026-05-01T09:01:00Z")

        after_batch = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert after_batch["status"] == "EXPIRED"
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["qa_status"] == "REJECTED"

        resp = api.complete_mix(batch["id"], batch_operator_headers)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)


class TestPackFillRoundingOrder:
    """Difficulty instance pack_fill_per_unit_rounding_order_mode_b."""

    def _setup(self):
        formulation, vessel = _base_formulation_and_vessel("EPX-RND-1")
        batch = create_mixed_batch(
            formulation["id"], vessel["id"], batch_volume_ml=1000
        )
        run = create_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=10,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        return batch, run

    def test_pack_fill_per_unit_rounding_computation(self, api, batch_operator_headers):
        """PRD §3.4: "The per-unit fill is the run's `unit_volume_ml` scaled by an overfill percentage keyed on `pack_format` — 2% for `CARTRIDGE`, 1% for `PAIL`, and 0.5% for `DRUM` — with the result rounded half-up to a whole millilitre and stored as `per_unit_fill_ml`. The number of `units_produced` is then the smaller of the requested `planned_units` and the whole number of per-unit fills that fit inside the batch's current `remaining_bulk_volume_ml` (that is, the floor of the remaining volume divided by the per-unit fill). `total_filled_ml` is `units_produced` multiplied by `per_unit_fill_ml`."

        Design: Difficulty/combinatorial_formula/pack_fill_per_unit_rounding_order_mode_b
        """
        batch, run = self._setup()
        completed = validate_success(api.complete_run(run["id"], batch_operator_headers))
        assert completed["per_unit_fill_ml"] == 316  # round_half_up(310 * 1.02) = round_half_up(316.2)
        assert completed["units_produced"] == 3  # min(10, floor(1000 / 316))
        assert completed["total_filled_ml"] == 948

    def test_pack_fill_per_unit_rounding_beats_sum_then_round(self, api, batch_operator_headers, plant_manager_headers):
        """PRD §3.4: "The per-unit-first order is normative: it can differ from computing the exact total and rounding once (three units of an exact 316.2 ml fill yield 949 ml under sum-then-round, versus 948 ml under the pinned per-unit-first order)."

        Design: Difficulty/combinatorial_formula/pack_fill_per_unit_rounding_order_mode_b
        """
        batch, run = self._setup()
        completed = validate_success(api.complete_run(run["id"], batch_operator_headers))
        # Pinned order: 3 x 316 = 948. The alternative (round(3 x 316.2) = 949) must NOT appear.
        assert completed["total_filled_ml"] == 948
        assert completed["total_filled_ml"] != 949
        batch_after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert batch_after["remaining_bulk_volume_ml"] == 52  # 1000 - 948


class TestPotLifeBoundaryOnRunComplete:
    """Difficulty instance pot_life_inclusive_boundary_on_run_complete."""

    def _setup(self):
        formulation, vessel = _base_formulation_and_vessel("EPX-POT-1", pot_life_minutes=120)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=2000)
        run1 = create_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        run2 = create_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:15:00Z", planned_end_at="2026-05-01T09:45:00Z",
        )
        return batch, run1, run2

    def test_complete_at_exact_pot_life_deadline_succeeds(self, api, batch_operator_headers):
        """PRD §2.6: "The batch is usable while elapsed time since `mixed_at` is less than or equal to the formulation's `pot_life_minutes` — the boundary is inclusive."

        Design: Difficulty/boundary_precision_check/pot_life_inclusive_boundary_on_run_complete
        """
        batch, run1, _run2 = self._setup()
        # mixed at 08:00, pot_life 120 -> deadline 10:00; elapsed == 120 at 10:00.
        set_clock("2026-05-01T10:00:00Z")
        completed = validate_success(api.complete_run(run1["id"], batch_operator_headers))
        assert completed["status"] == "SEALED"

    def test_complete_one_minute_past_deadline_fires_expiry_cascade(self, api, batch_operator_headers, plant_manager_headers, qa_manager_headers):
        """PRD §2.6: "If the deadline has passed, the batch expiry cascade fires (see §3.4) and the triggering call fails with `ERR_POT_LIFE_EXCEEDED`."
        PRD §3.4: "When a batch in `MIXED` or `PACKING` crosses its pot-life deadline and is touched, the expiry cascade moves the batch to `EXPIRED`, moves all of its `OPEN` and `HOLD` runs to `VOID`, rejects a lot still in `AWAITING_TEST`, `TESTING`, or `UNDER_REVIEW`, and — because units already sealed are unsalvageable — moves every unit of `SEALED` runs into condemnation: the lot's `units_condemned` grows by each such run's `units_produced` and the batch's `written_off_volume_ml` grows by each such run's `total_filled_ml`."

        Design: Difficulty/boundary_precision_check/pot_life_inclusive_boundary_on_run_complete
        """
        batch, run1, run2 = self._setup()
        lot_id = batch["production_lot_id"]
        set_clock("2026-05-01T10:00:00Z")
        validate_success(api.complete_run(run1["id"], batch_operator_headers))

        set_clock("2026-05-01T10:01:00Z")  # elapsed == 121 > 120
        resp = api.complete_run(run2["id"], batch_operator_headers)
        validate_error(resp, ApiErrorId.ERR_POT_LIFE_EXCEEDED)

        batch_after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert batch_after["status"] == "EXPIRED"
        run2_after = validate_success(api.get_packaging_run(run2["id"], plant_manager_headers))
        assert run2_after["status"] == "VOID"
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["qa_status"] == "REJECTED"


class TestVesselHalfOpenWindow:
    """Difficulty instance vessel_half_open_window_exclusion."""

    def test_adjacent_window_is_admitted(self, api, batch_operator_headers):
        """PRD §3.3: "The mix window is treated as a half-open interval that includes the start and excludes the end: a new batch overlaps an existing non-terminal batch on the same vessel (one in `MIXING`, `MIXED`, or `PACKING`) only when the new `mix_start_at` falls strictly before the existing batch's `mix_end_at` **and** the existing batch's `mix_start_at` falls strictly before the new `mix_end_at`; touching windows — where one batch's `mix_start_at` equals the other's `mix_end_at` — are permitted."

        Design: Difficulty/resource_temporal_overlap/vessel_half_open_window_exclusion
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-OVL-1")
        batch_a = create_batch(
            formulation["id"], vessel["id"],
            mix_start_at="2026-05-01T08:00:00Z", mix_end_at="2026-05-01T10:00:00Z",
            batch_volume_ml=1000,
        )
        assert batch_a["id"]
        # Adjacent: starts exactly when batch A ends — must be admitted.
        resp = api.create_batch(
            {
                "formulation_id": formulation["id"],
                "vessel_id": vessel["id"],
                "mix_start_at": "2026-05-01T10:00:00Z",
                "mix_end_at": "2026-05-01T12:00:00Z",
                "batch_volume_ml": 1000,
            },
            batch_operator_headers,
        )
        batch_b = validate_success(resp, expected_status=201)
        assert batch_b["id"]

    def test_straddling_window_is_rejected(self, api, batch_operator_headers, plant_manager_headers):
        """PRD §3.3: "a new batch overlaps an existing non-terminal batch on the same vessel (one in `MIXING`, `MIXED`, or `PACKING`) only when the new `mix_start_at` falls strictly before the existing batch's `mix_end_at` **and** the existing batch's `mix_start_at` falls strictly before the new `mix_end_at`; touching windows — where one batch's `mix_start_at` equals the other's `mix_end_at` — are permitted. Any genuine overlap is rejected with `ERR_VESSEL_TIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vessel_half_open_window_exclusion
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-OVL-1")
        create_batch(
            formulation["id"], vessel["id"],
            mix_start_at="2026-05-01T08:00:00Z", mix_end_at="2026-05-01T10:00:00Z",
            batch_volume_ml=1000,
        )
        create_batch(
            formulation["id"], vessel["id"],
            mix_start_at="2026-05-01T10:00:00Z", mix_end_at="2026-05-01T12:00:00Z",
            batch_volume_ml=1000,
        )
        # Straddles both windows.
        resp = api.create_batch(
            {
                "formulation_id": formulation["id"],
                "vessel_id": vessel["id"],
                "mix_start_at": "2026-05-01T09:00:00Z",
                "mix_end_at": "2026-05-01T11:00:00Z",
                "batch_volume_ml": 1000,
            },
            batch_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VESSEL_TIME_OVERLAP)

        data, meta = validate_paginated(
            api.list_batches(plant_manager_headers, params={"vessel_id": vessel["id"]})
        )
        assert meta["total_count"] == 2


class TestDryRoomClosedIntervalCapacity:
    """Difficulty instance dry_room_closed_interval_capacity_aggregate."""

    def _setup(self, api):
        formulation, vessel = _base_formulation_and_vessel(
            "SIL-OVL-2", capacity_liters=500, chemistry_family="SILICONE",
            moisture_sensitive=True, pot_life_minutes=480,
        )
        dry_room = create_dry_room("DR-OVL-2", max_concurrent_runs=2, humidity_limit_pct=10.0)
        batches = []
        for start, end in (("08:00", "08:10"), ("08:10", "08:20"), ("08:20", "08:30")):
            batch = create_batch(
                formulation["id"], vessel["id"],
                mix_start_at=f"2026-05-01T{start}:00Z", mix_end_at=f"2026-05-01T{end}:00Z",
                batch_volume_ml=5000,
            )
            batches.append(get_success_data(api.complete_mix(batch["id"], TEST_USERS_BO)))
        return formulation, vessel, dry_room, batches

    def test_touching_window_counts_but_fits_under_capacity(self, api, batch_operator_headers):
        """PRD §3.4: "The set of occupants is every run of the same room whose status is `OPEN` or `HOLD`, and window comparison uses **closed** interval semantics: an existing run overlaps the new one when the existing `planned_start_at` is at or before the new `planned_end_at` and the new `planned_start_at` is at or before the existing `planned_end_at` — touching windows count as overlapping because they share the boundary instant."

        Design: Difficulty/resource_temporal_overlap/dry_room_closed_interval_capacity_aggregate
        """
        _formulation, _vessel, dry_room, batches = self._setup(api)
        run1 = create_run(
            batches[0]["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=5,
            planned_start_at="2026-05-01T08:00:00Z", planned_end_at="2026-05-01T10:00:00Z",
            dry_room_id=dry_room["id"],
        )
        assert run1["id"]
        # Touching window [10:00,12:00] overlaps run1 under closed semantics but
        # count (1) is below capacity (2), so it is admitted.
        resp = api.create_packaging_run(
            {
                "batch_id": batches[1]["id"],
                "pack_format": "CARTRIDGE",
                "unit_volume_ml": 310,
                "planned_units": 5,
                "planned_start_at": "2026-05-01T10:00:00Z",
                "planned_end_at": "2026-05-01T12:00:00Z",
                "dry_room_id": dry_room["id"],
            },
            batch_operator_headers,
        )
        run2 = validate_success(resp, expected_status=201)
        assert run2["id"]

    def test_third_overlapping_run_exceeds_aggregate_capacity(self, api, batch_operator_headers):
        """PRD §3.4: "If the count of overlapping occupants has already reached the room's `max_concurrent_runs`, the new run is rejected with `ERR_DRY_ROOM_CAPACITY_EXCEEDED`. This is aggregate capacity, not exclusive use."

        Design: Difficulty/resource_temporal_overlap/dry_room_closed_interval_capacity_aggregate
        """
        _formulation, _vessel, dry_room, batches = self._setup(api)
        create_run(
            batches[0]["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=5,
            planned_start_at="2026-05-01T08:00:00Z", planned_end_at="2026-05-01T10:00:00Z",
            dry_room_id=dry_room["id"],
        )
        create_run(
            batches[1]["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=5,
            planned_start_at="2026-05-01T10:00:00Z", planned_end_at="2026-05-01T12:00:00Z",
            dry_room_id=dry_room["id"],
        )
        # [09:00,11:00] overlaps both existing runs: count 2 >= capacity 2.
        resp = api.create_packaging_run(
            {
                "batch_id": batches[2]["id"],
                "pack_format": "CARTRIDGE",
                "unit_volume_ml": 310,
                "planned_units": 5,
                "planned_start_at": "2026-05-01T09:00:00Z",
                "planned_end_at": "2026-05-01T11:00:00Z",
                "dry_room_id": dry_room["id"],
            },
            batch_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRY_ROOM_CAPACITY_EXCEEDED)


class TestPackagingConstraints:
    def test_pack_format_mismatch_on_second_run_returns_409(self, api, batch_operator_headers):
        """PRD §3.4: "All runs of a single batch must share the same `pack_format` and `unit_volume_ml` — the first run of the batch pins both onto the lot's `pack_format` and `unit_volume_ml`, moves the batch from `MIXED` to `PACKING`, and any later run whose `pack_format` or `unit_volume_ml` differs is rejected with `ERR_PACK_FORMAT_MISMATCH`."

        Design: Corner/errors/pack_format_mismatch_on_second_run_returns_409
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-PFM")
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=10000)
        create_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        resp = api.create_packaging_run(
            {
                "batch_id": batch["id"],
                "pack_format": "PAIL",
                "unit_volume_ml": 5000,
                "planned_units": 1,
                "planned_start_at": "2026-05-01T08:20:00Z",
                "planned_end_at": "2026-05-01T09:40:00Z",
            },
            batch_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PACK_FORMAT_MISMATCH)

    def test_run_complete_with_zero_producible_units_returns_422(self, api, batch_operator_headers, plant_manager_headers):
        """PRD §3.4: "If the allocation yields zero units, the completion is rejected with `ERR_INSUFFICIENT_BATCH_VOLUME`."

        Design: Corner/errors/run_complete_with_zero_producible_units_returns_422
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-ZRO")
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=100)
        run = create_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=1,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
        )
        resp = api.complete_run(run["id"], batch_operator_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BATCH_VOLUME)

        run_after = validate_success(api.get_packaging_run(run["id"], plant_manager_headers))
        assert run_after["status"] == "OPEN"
        batch_after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert batch_after["remaining_bulk_volume_ml"] == 100

    def test_derived_remaining_volume_reconciled_after_second_run(self, api, plant_manager_headers, qa_manager_headers):
        """PRD §3.4: "A successful completion moves the run to `SEALED`, decrements the batch's `remaining_bulk_volume_ml` by `total_filled_ml`, increments the lot's `units_filled` by `units_produced`, and — when the remaining bulk volume reaches exactly zero — transitions the batch from `PACKING` to `PACKED`."

        Design: Corner/cross_cutting_layers/derived_remaining_volume_reconciled_after_second_run
        """
        formulation, vessel = _base_formulation_and_vessel("EPX-DRV")
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=2000)
        lot_id = batch["production_lot_id"]
        run1 = create_and_complete_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:00:00Z",
        )
        assert run1["total_filled_ml"] == 948
        run2 = create_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:20:00Z", planned_end_at="2026-05-01T09:10:00Z",
        )
        completed2 = validate_success(api.complete_run(run2["id"], TEST_USERS_BO))
        assert completed2["total_filled_ml"] == 948

        batch_after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        assert batch_after["remaining_bulk_volume_ml"] == 104  # 2000 - 948 - 948
        assert batch_after["status"] == "PACKING"
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["units_filled"] == 6


class TestBatchVolumeConservation:
    """Difficulty instance batch_volume_conserved_across_pack_and_condemn."""

    def _setup(self):
        formulation, vessel = _base_formulation_and_vessel(
            "EPX-INV-1", chemistry_family="EPOXY", moisture_sensitive=True,
        )
        dry_room = create_dry_room("DR-INV-1", max_concurrent_runs=2, humidity_limit_pct=10.0)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=1000)
        lot_id = batch["production_lot_id"]
        run = create_and_complete_run(
            batch["id"], pack_format="CARTRIDGE", unit_volume_ml=310, planned_units=3,
            planned_start_at="2026-05-01T08:10:00Z", planned_end_at="2026-05-01T09:30:00Z",
            dry_room_id=dry_room["id"],
        )
        set_clock("2026-05-01T09:00:00Z")
        resp = api_client_create_exposure(run["id"], exposure_minutes=60, occurred_at="2026-05-01T08:50:00Z")
        assert resp.status_code == 201, f"Setup failed (exposure): {resp.text}"
        return batch, lot_id, run

    def test_condemn_moves_run_to_void_and_units_to_condemned(self, api, qa_manager_headers):
        """PRD §3.5: "With `outcome` `CONDEMN`, the run moves to `VOID`; if it had been `SEALED`, its units leave quarantine and enter condemnation — the lot's `units_quarantined` decreases by the run's `units_produced`, its `units_condemned` increases by the same amount, and the batch's `written_off_volume_ml` increases by the run's `total_filled_ml`, while `remaining_bulk_volume_ml` is **not** restored."

        Design: Difficulty/compensating_invariant/batch_volume_conserved_across_pack_and_condemn
        """
        _batch, lot_id, run = self._setup()
        resp = api.hold_release(run["id"], {"outcome": "CONDEMN", "note": "moisture ingress confirmed"}, qa_manager_headers)
        run_after = validate_success(resp)
        assert run_after["status"] == "VOID"

        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["units_condemned"] == 3
        assert lot["units_quarantined"] == 0
        assert lot["hold_status"] == "CLEAR"

    def test_condemn_does_not_restore_remaining_volume(self, api, qa_manager_headers, plant_manager_headers):
        """PRD §3.5: "With `outcome` `CONDEMN`, the run moves to `VOID`; if it had been `SEALED`, its units leave quarantine and enter condemnation — the lot's `units_quarantined` decreases by the run's `units_produced`, its `units_condemned` increases by the same amount, and the batch's `written_off_volume_ml` increases by the run's `total_filled_ml`, while `remaining_bulk_volume_ml` is **not** restored."

        Design: Difficulty/compensating_invariant/batch_volume_conserved_across_pack_and_condemn
        """
        batch, _lot_id, run = self._setup()
        resp = api.hold_release(run["id"], {"outcome": "CONDEMN", "note": "moisture ingress confirmed"}, qa_manager_headers)
        validate_success(resp)

        batch_after = validate_success(api.get_batch(batch["id"], plant_manager_headers))
        # Volume conservation: 52 remaining + 948 written off + 0 live == 1000 original.
        assert batch_after["remaining_bulk_volume_ml"] == 52
        assert batch_after["written_off_volume_ml"] == 948
        assert (
            batch_after["remaining_bulk_volume_ml"] + batch_after["written_off_volume_ml"]
            == batch_after["batch_volume_ml"] - 0
        )


# Local aliases kept at module scope to avoid circular fixture imports in tests.
from test_helpers import TEST_USERS, api_client  # noqa: E402

TEST_USERS_BO = TEST_USERS["batch_operator_headers"]


def api_client_create_exposure(run_id, exposure_minutes, occurred_at):
    return api_client.create_exposure_event(
        run_id,
        {"exposure_minutes": exposure_minutes, "occurred_at": occurred_at},
        TEST_USERS_BO,
    )
