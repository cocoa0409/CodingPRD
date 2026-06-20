"""Movement application: capacity gate, rest gap, AU reconciliation, OCC, revert ordering."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_herd,
    create_pasture,
    create_animal,
    create_weighed_animal,
    plan_movement,
    plan_and_apply_movement,
    ApiErrorId,
    TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]


class TestCapacityBoundary:
    def test_projection_equal_to_capacity_passes(self, api):
        """PRD §2.7: "The movement is rejected only when this projected aggregate is
        strictly greater than the pasture's `capacity_au`; a projection exactly equal
        to the capacity is allowed to proceed."

        Design: Difficulty/boundary_precision_check/pasture_capacity_strict_greater_than
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=1.0)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        mv = plan_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        animal_live = validate_success(api.get_animal(animal["id"], HM))
        applied = validate_success(
            api.apply_movement(
                mv["id"], {"expected_animal_version": animal_live["version"]}, HM
            )
        )
        assert applied["status"] == "APPLIED"
        pasture_after = validate_success(api.get_pasture(pen["id"], HM))
        assert pasture_after["current_au_load"] == 1.0

    def test_single_animal_just_over_capacity_rejected(self, api):
        """PRD §2.7: "The movement is rejected only when this projected aggregate is
        strictly greater than the pasture's `capacity_au`; a projection exactly equal
        to the capacity is allowed to proceed."

        Design: Difficulty/boundary_precision_check/pasture_capacity_strict_greater_than
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        # capacity 0.999 < one 454 kg animal's AU (1.0): projected 1.0 > 0.999 -> reject.
        pen = create_pasture(kind="PEN", capacity_au=0.999)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        mv = plan_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        animal_live = validate_success(api.get_animal(animal["id"], HM))
        resp = api.apply_movement(
            mv["id"], {"expected_animal_version": animal_live["version"]}, HM
        )
        validate_error(resp, ApiErrorId.ERR_PASTURE_OVER_CAPACITY.value)

    def test_projection_above_capacity_in_overlap_rejected(self, api):
        """PRD §3.8: "The capacity gate of §2.7 is then applied over the overlap window:
        if the unrounded projected aggregate AU at the destination during
        `[effective_from, effective_to)` together with the moving animal's AU would
        exceed the pasture's `capacity_au`, the application is rejected with
        `ERR_PASTURE_OVER_CAPACITY`".

        Design: Difficulty/resource_temporal_overlap/pasture_aggregate_au_capacity_overlap
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=1.0)
        a1 = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(a1["id"], pen["id"], "2026-03-21T00:00:00Z")
        a2 = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        mv2 = plan_movement(a2["id"], pen["id"], "2026-03-21T00:00:00Z")
        a2_live = validate_success(api.get_animal(a2["id"], HM))
        resp = api.apply_movement(
            mv2["id"], {"expected_animal_version": a2_live["version"]}, HM
        )
        validate_error(resp, ApiErrorId.ERR_PASTURE_OVER_CAPACITY.value)
        pasture_after = validate_success(api.get_pasture(pen["id"], HM))
        assert pasture_after["current_au_load"] == 1.0

    def test_two_animals_within_capacity_both_applied(self, api):
        """PRD §3.8: "if the unrounded projected aggregate AU at the destination during
        `[effective_from, effective_to)` together with the moving animal's AU would
        exceed the pasture's `capacity_au`, the application is rejected with
        `ERR_PASTURE_OVER_CAPACITY`; a projection exactly equal to capacity is
        permitted."

        Design: Difficulty/resource_temporal_overlap/pasture_aggregate_au_capacity_overlap
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        # capacity exactly 2.0 fits two 454 kg animals (aggregate 2.0 == capacity).
        pen = create_pasture(kind="PEN", capacity_au=2.0)
        a1 = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(a1["id"], pen["id"], "2026-03-21T00:00:00Z")
        a2 = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        mv2 = plan_movement(a2["id"], pen["id"], "2026-03-21T00:00:00Z")
        a2_live = validate_success(api.get_animal(a2["id"], HM))
        applied = validate_success(
            api.apply_movement(mv2["id"], {"expected_animal_version": a2_live["version"]}, HM)
        )
        assert applied["status"] == "APPLIED"
        pasture_after = validate_success(api.get_pasture(pen["id"], HM))
        assert pasture_after["current_au_load"] == 2.0


class TestRestPeriod:
    def test_reentry_too_soon_rejected(self, api):
        """PRD §3.8: "For a destination of `PASTURE` kind, the grazing rest gap is
        enforced: the new occupancy's `effective_from` must be at least the destination
        pasture's `rest_days` days after the prior occupancy's `effective_to` on that
        same pasture; a movement that begins too soon after the previous occupancy ended
        is rejected with `ERR_REST_PERIOD_VIOLATION`".

        Design: Difficulty/resource_temporal_overlap/pasture_grazing_rest_gap_adjacency
        """
        set_clock("2026-06-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        field = create_pasture(kind="PASTURE", capacity_au=50, rest_days=10)
        holding = create_pasture(kind="PEN", capacity_au=50)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(animal["id"], field["id"], "2026-04-01T00:00:00Z",
                                effective_to="2026-05-01T00:00:00Z")
        plan_and_apply_movement(animal["id"], holding["id"], "2026-05-01T00:00:00Z",
                                effective_to="2026-05-09T00:00:00Z")
        mv3 = plan_movement(animal["id"], field["id"], "2026-05-10T00:00:00Z")
        animal_live = validate_success(api.get_animal(animal["id"], HM))
        resp = api.apply_movement(
            mv3["id"], {"expected_animal_version": animal_live["version"]}, HM
        )
        validate_error(resp, ApiErrorId.ERR_REST_PERIOD_VIOLATION.value)

    def test_capacity_gate_not_applied_to_pen_rest(self, api):
        """PRD §3.8: "For a destination of `PASTURE` kind, the grazing rest gap is
        enforced ... (this gap is not enforced for a `PEN`)."

        Design: Difficulty/resource_temporal_overlap/pasture_grazing_rest_gap_adjacency
        """
        set_clock("2026-06-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=50, rest_days=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(animal["id"], pen["id"], "2026-04-01T00:00:00Z",
                                effective_to="2026-05-01T00:00:00Z")
        # A re-entry into the same PEN only 1 day after the prior occupancy ended:
        # rest gap is not enforced for PEN, so this must succeed.
        mv2 = plan_movement(animal["id"], pen["id"], "2026-05-02T00:00:00Z")
        animal_live = validate_success(api.get_animal(animal["id"], HM))
        applied = validate_success(
            api.apply_movement(
                mv2["id"], {"expected_animal_version": animal_live["version"]}, HM
            )
        )
        assert applied["status"] == "APPLIED"


class TestDerivedAuReconciliation:
    def test_reweigh_reconciles_pasture_and_herd_load(self, api):
        """PRD §2.7: "A pasture's `current_au_load` is the sum of the AU contributions
        of all animals whose `current_pasture_id` equals that pasture ... These loads
        are recomputed whenever an animal is created, a weight is recorded, a movement
        is applied or reverted, or an animal's life status changes."

        Design: Corner/cross_cutting_complexity_layers/derived_au_load_reconciles_after_weight_change
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        plan_and_apply_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        validate_success(
            api.create_weight(
                animal["id"], {"weighed_at": "2026-03-28", "weight_kg": 908.0}, HM
            ),
            expected_status=201,
        )
        pasture_after = validate_success(api.get_pasture(pen["id"], HM))
        herd_after = validate_success(api.get_herd(herd["id"], HM))
        assert pasture_after["current_au_load"] == 2.0
        assert herd_after["total_au_load"] == 2.0


class TestOptimisticConcurrency:
    def test_movement_apply_stale_animal_version_rejected(self, api):
        """PRD §2.6: "If the animal's current `version` has advanced beyond that value
        — because another writer has already applied a different movement, changing the
        animal's `current_pasture_id` and the animal-unit attribution — then this
        client's intended location change was computed against a stale location and is
        rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_complexity_layers/occ_movement_apply_stale_animal_version_returns_412
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen_a = create_pasture(kind="PEN", capacity_au=10)
        pen_b = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        stale_version = validate_success(api.get_animal(animal["id"], HM))["version"]
        mv_a = plan_movement(animal["id"], pen_a["id"], "2026-03-21T00:00:00Z")
        validate_success(
            api.apply_movement(mv_a["id"], {"expected_animal_version": stale_version}, HM)
        )
        mv_b = plan_movement(animal["id"], pen_b["id"], "2026-03-22T00:00:00Z")
        resp = api.apply_movement(
            mv_b["id"], {"expected_animal_version": stale_version}, HM
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


class TestMovementRequiresActiveAnimal:
    def test_apply_movement_on_culled_animal_rejected(self, api):
        """PRD §3.8: "Applying a planned movement is where the location and load
        actually change, and it is guarded by several checks. The animal must have
        `life_status` of `ACTIVE` or `SUSPENDED`."
        PRD §3.3: "operations that require an `ACTIVE` animal but find it `SUSPENDED`,
        `SOLD`, `DEAD`, or `CULLED` raise `ERR_ANIMAL_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/movement_apply_requires_animal_not_terminal
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        mv = plan_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        validate_success(api.set_life_status(animal["id"], {"to_status": "CULLED"}, HM))
        animal_live = validate_success(api.get_animal(animal["id"], HM))
        resp = api.apply_movement(
            mv["id"], {"expected_animal_version": animal_live["version"]}, HM
        )
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_ACTIVE.value)

    def test_apply_movement_on_active_animal_succeeds(self, api):
        """PRD §3.8: "Applying a planned movement is where the location and load
        actually change, and it is guarded by several checks. The animal must have
        `life_status` of `ACTIVE` or `SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/movement_apply_requires_animal_not_terminal
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        mv = plan_movement(animal["id"], pen["id"], "2026-03-21T00:00:00Z")
        animal_live = validate_success(api.get_animal(animal["id"], HM))
        applied = validate_success(
            api.apply_movement(
                mv["id"], {"expected_animal_version": animal_live["version"]}, HM
            )
        )
        assert applied["status"] == "APPLIED"


class TestRevertOrdering:
    def test_revert_non_latest_movement_rejected(self, api):
        """PRD §3.8: "a herd manager may revert a movement that is currently `APPLIED`,
        but only if it is the animal's most recently applied movement — if any later
        applied movement exists for that animal, the revert is rejected with
        `ERR_NOT_LATEST_MOVEMENT`".

        Design: Corner/state_machines/revert_non_latest_movement_returns_not_latest
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        pen_a = create_pasture(kind="PEN", capacity_au=10)
        pen_b = create_pasture(kind="PEN", capacity_au=10)
        animal = create_weighed_animal(herd["id"], 454.0, weighed_at="2026-03-20")
        mv_a = plan_and_apply_movement(animal["id"], pen_a["id"], "2026-03-21T00:00:00Z")
        plan_and_apply_movement(animal["id"], pen_b["id"], "2026-03-22T00:00:00Z")
        resp = api.revert_movement(mv_a["id"], HM)
        validate_error(resp, ApiErrorId.ERR_NOT_LATEST_MOVEMENT.value)
