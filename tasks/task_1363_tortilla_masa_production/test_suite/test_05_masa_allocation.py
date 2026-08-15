"""Masa allocation: boundary depletion, over-allocation, release idempotency,
batch from-state gating, and the conservation invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_masa,
    assert_batch_allocation,
    assert_masa_conservation,
    create_allocation_payload,
    create_line,
    create_product,
    create_run,
    evaluate_batch,
    mill_batch,
    setup_milled_batch,
    setup_steeping_batch,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SCHED = TEST_USERS["line_scheduler_headers"]
MILLER = TEST_USERS["miller_operator_headers"]


def _planned_run(sku="C-ALLOC", line_code="L-ALLOC", planned_cases=100):
    product = create_product(sku_code=sku)
    line = create_line(line_code=line_code)
    return create_run(product["id"], line["id"], planned_cases=planned_cases)


class TestAllocationBoundary:
    def test_allocate_exact_available_empties_batch(self, api):
        """PRD §3.3: "`allocated_kg` must be greater than zero and may not exceed
        the batch's current `masa_available_kg`; an over-allocation is rejected
        with `ERR_MASA_INSUFFICIENT`." and "the batch may auto-transition from
        `MASA_AVAILABLE` to terminal `DEPLETED` when `masa_available_kg` reaches
        zero and `actual_masa_kg` is greater than zero."
        Allocating exactly the 1552.0 kg available succeeds (inclusive boundary),
        drives availability to 0, and depletes the batch.

        Design: Difficulty/boundary_precision_check/masa_allocate_exact_available_empties_batch
        """
        ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-B3"})
        run = _planned_run("CORN-6-B3", "L-B3")
        allocation = allocate_masa(ctx["batch"]["id"], run["id"], 1552.0)
        assert_batch_allocation(allocation)
        assert allocation["allocation_status"] == "RESERVED"
        batch = validate_success(api.get_nixtamal_batch(ctx["batch"]["id"], MILLER))
        assert batch["masa_available_kg"] == pytest.approx(0)
        assert batch["batch_status"] == "DEPLETED"

    def test_exact_allocation_preserves_conservation_invariant(self, api):
        """PRD §2.10: "The **masa conservation invariant** states that for any
        nixtamal batch, `actual_masa_kg` always equals `masa_available_kg` plus
        the sum of `allocated_kg` over that batch's allocations in `RESERVED` or
        `CONSUMED`."
        After reserving the full 1552.0 kg: 1552.0 == 0 + 1552.0.

        Design: Difficulty/boundary_precision_check/masa_allocate_exact_available_empties_batch
        """
        ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-B3"})
        run = _planned_run("CORN-6-B3", "L-B3")
        allocation = allocate_masa(ctx["batch"]["id"], run["id"], 1552.0)
        batch = validate_success(api.get_nixtamal_batch(ctx["batch"]["id"], MILLER))
        assert_masa_conservation(batch, 1552.0)
        assert allocation["allocated_kg"] == pytest.approx(1552.0)

    def test_over_allocation_rejected_and_batch_untouched(self, api):
        """PRD §3.3: "`allocated_kg` must be greater than zero and may not exceed
        the batch's current `masa_available_kg`; an over-allocation is rejected
        with `ERR_MASA_INSUFFICIENT`."
        2000 kg against 1552.0 kg available -> rejected; availability unchanged.

        Design: Corner/validations/val_masa_insufficient_allocation
        """
        ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-MI"})
        run = _planned_run("C-MI", "L-MI", planned_cases=50)
        validate_error(
            api.create_allocation(
                create_allocation_payload(ctx["batch"]["id"], run["id"],
                                          allocated_kg=2000),
                SCHED,
            ),
            ApiErrorId.ERR_MASA_INSUFFICIENT,
        )
        batch = validate_success(api.get_nixtamal_batch(ctx["batch"]["id"], SCHED))
        assert batch["masa_available_kg"] == pytest.approx(1552.0)


class TestReleaseIdempotencyAndConservation:
    def test_allocate_then_release_conserves_total(self, api):
        """PRD §2.10: "Allocation moves kilograms from `masa_available_kg` into
        `RESERVED`; release moves them back; consume re-labels `RESERVED` to
        `CONSUMED` — the forward and compensating pair leaves the sum unchanged."
        After allocate(100): 1552.0 == 1452.0 + 100.

        Design: Difficulty/compensating_invariant/masa_allocate_release_conserves_total
        """
        ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-C1"})
        run = _planned_run("CORN-6-C1", "L-C1")
        allocate_masa(ctx["batch"]["id"], run["id"], 100)
        batch = validate_success(api.get_nixtamal_batch(ctx["batch"]["id"], SCHED))
        assert batch["masa_available_kg"] == pytest.approx(1452.0)
        assert_masa_conservation(batch, 100.0)

    def test_release_restores_availability(self, api):
        """PRD §3.3: "Releasing an allocation flips it from `RESERVED` to terminal
        `RELEASED`, adds `allocated_kg` back to the batch's `masa_available_kg`,
        and recomputes the run's `masa_reserved_kg`".
        Forward + compensating pair: availability returns to exactly 1552.0.

        Design: Difficulty/compensating_invariant/masa_allocate_release_conserves_total
        """
        ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-C1"})
        run = _planned_run("CORN-6-C1", "L-C1")
        allocation = allocate_masa(ctx["batch"]["id"], run["id"], 100)
        released = validate_success(api.release_allocation(allocation["id"], SCHED))
        assert released["allocation_status"] == "RELEASED"
        batch = validate_success(api.get_nixtamal_batch(ctx["batch"]["id"], SCHED))
        assert batch["masa_available_kg"] == pytest.approx(1552.0)
        assert_masa_conservation(batch, 0.0)

    def test_release_twice_rejected_without_double_restore(self, api):
        """PRD §3.3: "Both release and consume require the allocation to
        currently be in `RESERVED` — otherwise `ERR_ALLOCATION_INVALID_STATE`".
        A second release must fail and must not credit the batch again.

        Design: Corner/state_machines/sm_allocation_release_twice_rejected
        """
        ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-AR"})
        run = _planned_run("SM-AR", "L-AR", planned_cases=50)
        allocation = allocate_masa(ctx["batch"]["id"], run["id"], 100)
        validate_success(api.release_allocation(allocation["id"], SCHED))
        validate_error(
            api.release_allocation(allocation["id"], SCHED),
            ApiErrorId.ERR_ALLOCATION_INVALID_STATE,
        )
        batch = validate_success(api.get_nixtamal_batch(ctx["batch"]["id"], SCHED))
        assert batch["masa_available_kg"] == pytest.approx(1552.0)


class TestAllocationBatchFromState:
    def test_allocation_against_steeping_batch_rejected(self, api):
        """PRD §3.3: "A `LineScheduler` reserves masa from a batch in
        `MASA_AVAILABLE` for a run in `PLANNED` or `SCHEDULED` by creating a batch
        allocation naming `nixtamal_batch_id`, `production_run_id`, and
        `allocated_kg`." A batch still in STEEPING fails the target-entity
        from-state check (§2.9 item 5 lists `ERR_BATCH_INVALID_STATE` among the
        state errors).

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_until_batch_masa_available
        """
        ctx = setup_steeping_batch(lot_overrides={"lot_code": "LOT-X3"})
        run = _planned_run("CORN-6-X3", "L-X3")
        validate_error(
            api.create_allocation(
                create_allocation_payload(ctx["batch"]["id"], run["id"],
                                          allocated_kg=388.8),
                SCHED,
            ),
            ApiErrorId.ERR_BATCH_INVALID_STATE,
        )

    def test_allocation_succeeds_once_masa_available(self, api):
        """PRD §3.3: "A `LineScheduler` reserves masa from a batch in
        `MASA_AVAILABLE` for a run in `PLANNED` or `SCHEDULED` by creating a batch
        allocation naming `nixtamal_batch_id`, `production_run_id`, and
        `allocated_kg`." and "Creation subtracts `allocated_kg` from the batch's
        `masa_available_kg`, recomputes the run's `masa_reserved_kg` (the sum of
        `allocated_kg` over that run's `RESERVED` allocations), and enters the
        allocation in `allocation_status` `RESERVED`."
        After evaluate+mill the identical allocation succeeds: 1552.0 - 388.8 =
        1163.2 kg remain.

        Design: Difficulty/cross_entity_state_dependency/allocation_blocked_until_batch_masa_available
        """
        ctx = setup_steeping_batch(lot_overrides={"lot_code": "LOT-X3"})
        run = _planned_run("CORN-6-X3", "L-X3")
        evaluate_batch(ctx["batch"]["id"], "PASS")
        mill_batch(ctx["batch"]["id"])
        allocation = allocate_masa(ctx["batch"]["id"], run["id"], 388.8)
        assert allocation["allocation_status"] == "RESERVED"
        batch = validate_success(api.get_nixtamal_batch(ctx["batch"]["id"], SCHED))
        assert batch["masa_available_kg"] == pytest.approx(1163.2, abs=1e-6)
