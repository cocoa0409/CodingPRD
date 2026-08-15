"""Lot allocation gates: lot release state, weight budget, duplicate and
type/grade matching, OCC on the batch version, exact fill, and the
single-lot dominance ceiling.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate,
    create_active_recipe,
    create_allocation_payload,
    create_batch,
    create_graded_lot,
    create_lab_submitted_lot,
    create_locked_batch_with_allocations,
    create_released_lot,
    create_supplier,
    get_batch,
    get_lot,
    lock_recipe,
    single_component,
    validate_error,
    validate_paginated,
    validate_success,
)

BM = TEST_USERS["blend_master_headers"]


def _locked_batch(recipe_id, target_weight_kg=10.0):
    batch = create_batch(recipe_id, target_weight_kg)
    return lock_recipe(batch["id"])


class TestAllocationLotReleaseGate:
    def test_allocation_from_lab_submitted_lot_rejected(self, api):
        """PRD §3.4: "The lot must currently be `RELEASED`; any other lot
        status is `ERR_LOT_NOT_RELEASED`."

        The lot has passed its lab gate (LAB_SUBMITTED) but was never
        QA-released, so the allocation is rejected.

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_lot_released
        """
        supplier = create_supplier(name="Gate Co")
        lot = create_lab_submitted_lot(supplier["id"], leaf_type="BLACK",
                                       weight_kg=20.0,
                                       measured_residue_ppm=0.30)
        recipe = create_active_recipe(
            pack_format="TEA_BAG",
            components=[single_component("BLACK", "B", 100.0)])
        batch = _locked_batch(recipe["id"], 10.0)

        res = api.create_allocation(
            batch["id"],
            create_allocation_payload(lot["id"], 10.0, batch["version"]), BM)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_RELEASED)
        _, meta = validate_paginated(
            api.list_batch_allocations(batch["id"], BM))
        assert meta["total_count"] == 0

    def test_allocation_from_graded_lot_rejected(self, api):
        """PRD §3.4: "The lot must currently be `RELEASED`; any other lot
        status is `ERR_LOT_NOT_RELEASED`."

        A GRADED lot (no residue test at all) is just as unallocatable.

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_lot_released
        """
        supplier = create_supplier(name="Gate Co 2")
        lot = create_graded_lot(supplier["id"], leaf_type="BLACK",
                                weight_kg=20.0)
        recipe = create_active_recipe(
            pack_format="TEA_BAG",
            components=[single_component("BLACK", "B", 100.0)])
        batch = _locked_batch(recipe["id"], 10.0)

        res = api.create_allocation(
            batch["id"],
            create_allocation_payload(lot["id"], 10.0, batch["version"]), BM)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_RELEASED)


class TestAllocationMatching:
    def test_allocation_exceeds_remaining_rejected(self, api):
        """PRD §3.4: "The draw must be strictly positive and no greater
        than the lot's `remaining_weight_kg`; overdraws fail with
        `ERR_LOT_WEIGHT_EXCEEDED`."

        Design: Corner/validations/allocation_exceeds_remaining_rejected
        """
        supplier = create_supplier(name="W Co")
        lot = create_released_lot(supplier["id"], leaf_type="BLACK",
                                  weight_kg=20.0)
        recipe = create_active_recipe(
            name="RW", pack_format="TEA_BAG",
            components=[single_component("BLACK", "C", 100.0)])
        batch = _locked_batch(recipe["id"], 10.0)

        res = api.create_allocation(
            batch["id"],
            create_allocation_payload(lot["id"], 25.0, batch["version"]), BM)
        validate_error(res, ApiErrorId.ERR_LOT_WEIGHT_EXCEEDED)
        _, meta = validate_paginated(
            api.list_batch_allocations(batch["id"], BM))
        assert meta["total_count"] == 0

    def test_duplicate_lot_allocation_rejected(self, api):
        """PRD §3.4: "Nor may the same lot be drawn twice into one batch: a
        second `ACTIVE` allocation against an already-allocated lot is
        rejected with `ERR_DUPLICATE_LOT_ALLOCATION`."

        The second attempt carries the fresh OCC batch version, proving the
        rejection is the duplicate rule, not staleness.

        Design: Corner/validations/duplicate_lot_allocation_rejected
        """
        supplier = create_supplier(name="Dup Co")
        lot = create_released_lot(supplier["id"], leaf_type="BLACK",
                                  weight_kg=60.0)
        recipe = create_active_recipe(
            name="RD", pack_format="TEA_BAG",
            components=[single_component("BLACK", "C", 100.0)])
        batch = _locked_batch(recipe["id"], 20.0)
        allocate(batch["id"], lot["id"], 10.0)

        fresh_version = get_batch(batch["id"])["version"]
        res = api.create_allocation(
            batch["id"],
            create_allocation_payload(lot["id"], 5.0, fresh_version), BM)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_LOT_ALLOCATION)
        _, meta = validate_paginated(
            api.list_batch_allocations(batch["id"], BM))
        assert meta["total_count"] == 1

    def test_allocation_type_mismatch_rejected(self, api):
        """PRD §3.4: "The lot's `leaf_type` must match some component of
        the recipe, else `ERR_ALLOCATION_TYPE_MISMATCH`."

        Design: Corner/validations/allocation_type_mismatch_rejected
        """
        supplier = create_supplier(name="Type Co")
        lot = create_released_lot(supplier["id"], leaf_type="GREEN",
                                  weight_kg=30.0, aroma_score=90,
                                  briskness_score=88, appearance_score=92)
        recipe = create_active_recipe(
            name="RTy", pack_format="TEA_BAG",
            components=[single_component("BLACK", "C", 100.0)])
        batch = _locked_batch(recipe["id"], 10.0)

        res = api.create_allocation(
            batch["id"],
            create_allocation_payload(lot["id"], 10.0, batch["version"]), BM)
        validate_error(res, ApiErrorId.ERR_ALLOCATION_TYPE_MISMATCH)

    def test_allocation_grade_too_low_rejected(self, api):
        """PRD §3.4: "And the lot's `composite_grade` must satisfy the
        matched component's `min_grade`, else
        `ERR_ALLOCATION_GRADE_TOO_LOW`."
        PRD §3.3: "Grade ordering is `A` above `B` above `C`, and a lot
        satisfies a component's `min_grade` when its own `composite_grade`
        ranks at or above that minimum."

        A 75.0 composite is grade B, below the component's min_grade A.

        Design: Corner/validations/allocation_grade_too_low_rejected
        """
        supplier = create_supplier(name="GradeLow Co")
        lot = create_released_lot(supplier["id"], leaf_type="BLACK",
                                  weight_kg=30.0, aroma_score=75,
                                  briskness_score=75, appearance_score=75)
        assert get_lot(lot["id"])["composite_grade"] == "B"
        recipe = create_active_recipe(
            name="RG", pack_format="TEA_BAG",
            components=[single_component("BLACK", "A", 100.0)])
        batch = _locked_batch(recipe["id"], 10.0)

        res = api.create_allocation(
            batch["id"],
            create_allocation_payload(lot["id"], 10.0, batch["version"]), BM)
        validate_error(res, ApiErrorId.ERR_ALLOCATION_GRADE_TOO_LOW)


class TestAllocationOCC:
    def test_occ_allocation_stale_rejected(self, api):
        """PRD §2.7: "A request to `POST /tea-ops/batches/{id}/allocations`
        must include `expected_batch_version`, holding the batch `version`
        the client last observed; if the batch's current `version` differs
        — because another writer has since mutated the batch, for example
        by adding an allocation of their own — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "increments the batch's `version` by one."

        Design: Corner/complexity_layers/occ_allocation_stale_rejected
        """
        supplier = create_supplier(name="Occ Co")
        lot1 = create_released_lot(supplier["id"], leaf_type="BLACK",
                                   weight_kg=60.0, harvest_date="2026-02-01")
        lot2 = create_released_lot(supplier["id"], leaf_type="BLACK",
                                   weight_kg=40.0, harvest_date="2026-02-02")
        recipe = create_active_recipe(
            name="ROA", pack_format="TEA_BAG",
            components=[single_component("BLACK", "C", 100.0)])
        batch = _locked_batch(recipe["id"], 20.0)
        stale_version = batch["version"]

        allocate(batch["id"], lot1["id"], 10.0)  # bumps batch version

        res = api.create_allocation(
            batch["id"],
            create_allocation_payload(lot2["id"], 5.0, stale_version), BM)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        _, meta = validate_paginated(
            api.list_batch_allocations(batch["id"], BM))
        assert meta["total_count"] == 1, "stale write must not persist"


def test_allocation_reverse_get_computed_read(api):
    """PRD §3.4: "Every accepted allocation persists with its `batch_id`,
    starts `ACTIVE`, books its `line_cost_cents` as the allocated
    kilograms times the lot's `cost_per_kg_cents` rounded half-up to whole
    cents"
    PRD §2.11: "Resources are addressed flatly by `id`, with
    sub-collections nested under their owner — grade assessments, residue
    tests, and allocations under a leaf lot; allocations and flavoring
    applications under a batch"

    10.0 kg at 900 cents/kg books line_cost_cents 9000, visible from both
    FK reverse channels.

    Design: Corner/endpoints/allocation_reverse_get_computed_read
    """
    supplier = create_supplier(name="Rev Co")
    lot = create_released_lot(supplier["id"], leaf_type="BLACK",
                              weight_kg=60.0, cost_per_kg_cents=900)
    recipe = create_active_recipe(
        name="RRev", pack_format="TEA_BAG",
        components=[single_component("BLACK", "C", 100.0)])
    batch = create_locked_batch_with_allocations(
        recipe["id"], 20.0, [(lot["id"], 10.0)])

    batch_side, meta_b = validate_paginated(
        api.list_batch_allocations(batch["id"], BM))
    assert meta_b["total_count"] == 1
    assert batch_side[0]["line_cost_cents"] == 9000
    assert batch_side[0]["batch_id"] == batch["id"]
    assert batch_side[0]["status"] == "ACTIVE"

    lot_side, meta_l = validate_paginated(
        api.list_lot_allocations(lot["id"], BM))
    assert meta_l["total_count"] == 1
    assert lot_side[0]["id"] == batch_side[0]["id"], (
        "both FK reverse channels return the same allocation")


class TestFinalization:
    def test_fill_incomplete_rejected(self, api):
        """PRD §3.4: "For every required component, the kilograms covered
        by `ACTIVE` allocations drawn from lots of the component's leaf
        type whose grade meets the `min_grade` must equal the component's
        `required_kg` exactly, compared at three-decimal precision; any
        shortfall or overshoot is rejected with `ERR_FILL_INCOMPLETE`."

        18.0 kg allocated against a 20.0 kg requirement.

        Design: Corner/validations/fill_incomplete_rejected
        """
        supplier = create_supplier(name="Fill Co")
        lot = create_released_lot(supplier["id"], leaf_type="BLACK",
                                  weight_kg=60.0)
        recipe = create_active_recipe(
            name="RFi", pack_format="TEA_BAG",
            components=[single_component("BLACK", "C", 100.0)])
        batch = create_locked_batch_with_allocations(
            recipe["id"], 20.0, [(lot["id"], 18.0)])

        res = api.finalize_allocation(batch["id"], BM)
        validate_error(res, ApiErrorId.ERR_FILL_INCOMPLETE)
        assert get_batch(batch["id"])["status"] == "RECIPE_LOCKED"

    def test_single_lot_dominance_rejected(self, api):
        """PRD §3.4: "Blend consistency adds a dominance ceiling: for any
        component whose `required_kg` exceeds 25.0 kg, no single lot may
        supply more than 70 percent of that component — a share strictly
        above 0.70 violates the rule, while a share of exactly 0.70 is
        permitted — and a breach is rejected with
        `ERR_SINGLE_LOT_DOMINANCE`."

        30.0 + 10.0 against a 40.0 kg requirement is a 75% single-lot
        share.

        Design: Corner/validations/single_lot_dominance_rejected
        """
        supplier = create_supplier(name="Dom Co")
        lot1 = create_released_lot(supplier["id"], leaf_type="BLACK",
                                   weight_kg=60.0, harvest_date="2026-02-01")
        lot2 = create_released_lot(supplier["id"], leaf_type="BLACK",
                                   weight_kg=40.0, harvest_date="2026-02-02")
        recipe = create_active_recipe(
            name="RDo", pack_format="TEA_BAG",
            components=[single_component("BLACK", "C", 100.0)])
        batch = create_locked_batch_with_allocations(
            recipe["id"], 40.0, [(lot1["id"], 30.0), (lot2["id"], 10.0)])

        res = api.finalize_allocation(batch["id"], BM)
        validate_error(res, ApiErrorId.ERR_SINGLE_LOT_DOMINANCE)
        assert get_batch(batch["id"])["status"] == "RECIPE_LOCKED"
