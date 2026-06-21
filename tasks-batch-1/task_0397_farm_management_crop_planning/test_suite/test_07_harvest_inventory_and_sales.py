"""Harvest-lot grading, the parallel quality/sale axes, and sale-contract
commit / fill / ship / cancel workflows with their cascades.

Difficulty queue A: non_linear_state_machine (parallel quality x sale axes),
transitive_cascade (cancel contract releases lot), priority_pair_validation_conflict
(referential beats fiscal on commit), cross_entity_state_dependency (commit
depends on contract OPEN state).
Corner queue B: state_machines (grade-already-graded, ship cascade, ship-not-filled),
endpoints (quality insufficient, overcommit).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_sale_contract,
    setup_graded_lot, setup_partially_committed_contract, setup_filled_contract,
    commit_lot,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine — harvest_lot_parallel_quality_and_sale_axes
# ===========================================================================
def test_lot_parallel_axes_quality_and_sale_independent(api):
    """PRD §3.6: "A lot carries two *independent* state dimensions. The quality axis,
    `quality_status`, starts at `UNGRADED`. The sale axis, `sale_status`, starts at
    `IN_INVENTORY`".
    PRD §3.9: "a partial fill of the lot moves it from `IN_INVENTORY` to
    `PARTIALLY_COMMITTED`".

    Design: Difficulty/non_linear_state_machine/harvest_lot_parallel_quality_and_sale_axes_independent
    """
    ctx = setup_graded_lot(crop="CORN", quantity=1000.0, grade="GRADE_A")
    contract = create_sale_contract(crop="CORN", contracted_quantity=2000.0,
                                    price_per_unit=5.0, min_quality="GRADE_B")
    sc = validate_success(api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 400.0}, SA))
    lot = validate_success(api.get_harvest_lot(ctx["lot"]["id"], FM))
    assert lot["quality_status"] == "GRADE_A", f"quality axis must stay GRADE_A, got {lot['quality_status']}"
    assert lot["sale_status"] == "PARTIALLY_COMMITTED", (
        f"sale axis must be PARTIALLY_COMMITTED, got {lot['sale_status']}")
    assert lot["quantity_committed"] == 400, f"quantity_committed must be 400, got {lot['quantity_committed']}"
    assert sc["committed_quantity"] == 400, f"contract committed must be 400, got {sc['committed_quantity']}"
    assert sc["status"] == "PARTIALLY_FILLED", f"contract must be PARTIALLY_FILLED, got {sc['status']}"


def test_lot_commit_sets_committed_contract_and_value(api):
    """PRD §3.9: "A successful commit raises the lot's `quantity_committed`, sets the
    lot's `committed_contract_id`, and advances the lot's `sale_status`".
    PRD §3.9: "the contract's `committed_quantity` and `contract_value` (its
    `committed_quantity` multiplied by `price_per_unit`, rounded to two decimal places)
    are recomputed".

    Design: Difficulty/non_linear_state_machine/harvest_lot_parallel_quality_and_sale_axes_independent
    """
    ctx = setup_graded_lot(crop="CORN", quantity=1000.0, grade="GRADE_A")
    contract = create_sale_contract(crop="CORN", contracted_quantity=2000.0,
                                    price_per_unit=5.0, min_quality="GRADE_B")
    sc = validate_success(api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 400.0}, SA))
    lot = validate_success(api.get_harvest_lot(ctx["lot"]["id"], FM))
    assert lot["committed_contract_id"] == contract["id"], (
        f"committed_contract_id must be set to the contract, got {lot['committed_contract_id']}")
    assert sc["contract_value"] == 2000.00, (
        f"contract_value must be 400*5 = 2000.00, got {sc['contract_value']}")


# ===========================================================================
# Difficulty: transitive_cascade — cancel_contract_cascade_depth2_release_lot
# ===========================================================================
def test_cancel_partially_filled_contract_releases_lot(api):
    """PRD §3.9: "Cancelling a `PARTIALLY_FILLED` contract releases every committed lot:
    each such lot has its `quantity_committed` reset to zero, its `committed_contract_id`
    cleared to null, and its `sale_status` returned to `IN_INVENTORY`, and the contract's
    `committed_quantity` and `contract_value` are recomputed accordingly."

    Design: Difficulty/transitive_cascade/cancel_contract_cascade_depth2_release_lot
    """
    ctx = setup_partially_committed_contract(
        lot_quantity=1000.0, contracted_quantity=2000.0, commit_quantity=400.0,
        price_per_unit=5.0, crop="CORN", grade="GRADE_A")
    cancelled = validate_success(api.cancel_contract(ctx["contract"]["id"], SA))
    assert cancelled["status"] == "CANCELLED", f"contract must be CANCELLED, got {cancelled['status']}"
    assert cancelled["committed_quantity"] == 0, (
        f"contract committed_quantity must recompute to 0, got {cancelled['committed_quantity']}")
    lot = validate_success(api.get_harvest_lot(ctx["lot"]["id"], FM))
    assert lot["sale_status"] == "IN_INVENTORY", (
        f"lot must return to IN_INVENTORY, got {lot['sale_status']}")
    assert lot["quantity_committed"] == 0, (
        f"lot quantity_committed must reset to 0, got {lot['quantity_committed']}")


def test_cancel_partially_filled_clears_committed_contract_id(api):
    """PRD §3.9: "each such lot has its `quantity_committed` reset to zero, its
    `committed_contract_id` cleared to null, and its `sale_status` returned to
    `IN_INVENTORY`".

    Design: Difficulty/transitive_cascade/cancel_contract_cascade_depth2_release_lot
    """
    ctx = setup_partially_committed_contract(
        lot_quantity=1000.0, contracted_quantity=2000.0, commit_quantity=400.0,
        price_per_unit=5.0, crop="CORN", grade="GRADE_A")
    validate_success(api.cancel_contract(ctx["contract"]["id"], SA))
    lot = validate_success(api.get_harvest_lot(ctx["lot"]["id"], FM))
    assert lot["committed_contract_id"] is None, (
        f"committed_contract_id must clear to null, got {lot['committed_contract_id']}")


# ===========================================================================
# Difficulty: priority_pair_validation_conflict — referential_beats_fiscal_on_commit
# ===========================================================================
def test_crop_mismatch_beats_overcommit_on_commit(api):
    """PRD §3.9: "The crop must match: the `crop` of the plan behind the lot must equal
    the contract's `crop`, else `ERR_CROP_MISMATCH`."
    PRD §2.10: "Cross-aggregate referential coherence is evaluated next where it applies
    (priority above the safety, temporal, rate, and fiscal families)."
    PRD §2.10: "Inventory sufficiency (seed waterfall coverage and contract overcommit)
    follows."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_commit_crop_mismatch_and_overcommit
    """
    # SOY GRADE_A lot 1000; CORN contract contracted 500; commit 1000 -> both crop
    # mismatch and overcommit; referential precedence returns ERR_CROP_MISMATCH.
    ctx = setup_graded_lot(crop="SOY", quantity=1000.0, grade="GRADE_A")
    contract = create_sale_contract(crop="CORN", contracted_quantity=500.0, price_per_unit=5.0)
    resp = api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 1000.0}, SA)
    validate_error(resp, ApiErrorId.ERR_CROP_MISMATCH.value)


def test_crop_mismatch_alone_rejected_on_commit(api):
    """PRD §3.9: "The crop must match: the `crop` of the plan behind the lot must equal
    the contract's `crop`, else `ERR_CROP_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_commit_crop_mismatch_and_overcommit
    """
    # SOY lot, CORN contract sized large enough that overcommit can't fire; only crop mismatch.
    ctx = setup_graded_lot(crop="SOY", quantity=1000.0, grade="GRADE_A")
    contract = create_sale_contract(crop="CORN", contracted_quantity=5000.0, price_per_unit=5.0)
    resp = api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 500.0}, SA)
    validate_error(resp, ApiErrorId.ERR_CROP_MISMATCH.value)


# ===========================================================================
# Difficulty: cross_entity_state_dependency — lot_commit_depends_on_contract_open_state
# ===========================================================================
def test_commit_to_cancelled_contract_invalid_state(api):
    """PRD §3.9: "`SHIPPED` and `CANCELLED` are terminal for a contract."
    PRD §2.10: "the target resource must be in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/lot_commit_depends_on_contract_open_state
    """
    ctx = setup_graded_lot(crop="CORN", quantity=1000.0, grade="GRADE_A")
    contract = create_sale_contract(crop="CORN", contracted_quantity=2000.0, price_per_unit=5.0)
    validate_success(api.cancel_contract(contract["id"], SA))
    resp = api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 100.0}, SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_commit_to_open_contract_succeeds(api):
    """PRD §3.9: "A new contract is `OPEN` with `committed_quantity` zero and
    `contract_value` zero." PRD §3.9: "a contract whose committed quantity is still below
    contracted moves from `OPEN` to `PARTIALLY_FILLED`".

    Design: Difficulty/cross_entity_state_dependency/lot_commit_depends_on_contract_open_state
    """
    ctx = setup_graded_lot(crop="CORN", quantity=1000.0, grade="GRADE_A")
    contract = create_sale_contract(crop="CORN", contracted_quantity=2000.0, price_per_unit=5.0)
    sc = validate_success(api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 100.0}, SA))
    assert sc["status"] == "PARTIALLY_FILLED", (
        f"OPEN contract must advance to PARTIALLY_FILLED on partial commit, got {sc['status']}")


# ===========================================================================
# Corner: grading, ship cascade, ship-not-filled, quality insufficient, overcommit
# ===========================================================================
def test_grade_already_graded_lot_rejected(api):
    """PRD §3.6: "Grading is an `Agronomist` action on the quality axis and is only
    permitted while the lot is `UNGRADED`; grading an already-graded lot is rejected with
    `ERR_LOT_ALREADY_GRADED`."

    Design: Corner/state_machines/grade_already_graded_lot_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_graded_lot(crop="CORN", quantity=500.0, grade="GRADE_A")
    resp = api.grade_harvest_lot(ctx["lot"]["id"], {"grade": "GRADE_B"}, AG)
    validate_error(resp, ApiErrorId.ERR_LOT_ALREADY_GRADED.value)


def test_ship_filled_contract_cascades_lots_to_shipped(api):
    """PRD §3.9: "Shipping cascades to inventory: every harvest lot whose
    `committed_contract_id` is this contract has its `sale_status` advanced from
    `FULLY_COMMITTED` to `SHIPPED`, which is terminal for the lot and freezes it."

    Design: Corner/state_machines/ship_contract_cascades_lots_to_shipped
    """
    ctx = setup_filled_contract(lot_quantity=1000.0, contracted_quantity=1000.0,
                                price_per_unit=5.0, crop="CORN", grade="GRADE_A")
    shipped = validate_success(api.ship_contract(ctx["contract"]["id"], SA))
    assert shipped["status"] == "SHIPPED", f"contract must be SHIPPED, got {shipped['status']}"
    lot = validate_success(api.get_harvest_lot(ctx["lot"]["id"], FM))
    assert lot["sale_status"] == "SHIPPED", f"lot must cascade to SHIPPED, got {lot['sale_status']}"


def test_ship_contract_not_filled_rejected(api):
    """PRD §3.9: "Shipping is a `SalesAgent` action permitted only on a `FILLED`
    contract, moving it from `FILLED` to `SHIPPED`; attempting to ship a contract that is
    not `FILLED` is rejected with `ERR_CONTRACT_NOT_FILLED`."

    Design: Corner/state_machines/ship_contract_not_filled_rejected
    """
    contract = create_sale_contract(crop="CORN", contracted_quantity=1000.0, price_per_unit=5.0)
    resp = api.ship_contract(contract["id"], SA)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FILLED.value)


def test_commit_lot_quality_insufficient(api):
    """PRD §3.9: "The lot's `quality_status` must be `GRADE_A` or `GRADE_B` and must meet
    or exceed the contract's `min_quality`; an `UNGRADED`, `REJECTED`, or
    insufficiently-graded lot is rejected with `ERR_LOT_QUALITY_INSUFFICIENT`."

    Design: Corner/endpoints/commit_lot_quality_insufficient
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_graded_lot(crop="CORN", quantity=500.0, grade="GRADE_B")
    contract = create_sale_contract(crop="CORN", contracted_quantity=1000.0,
                                    price_per_unit=5.0, min_quality="GRADE_A")
    resp = api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 100.0}, SA)
    validate_error(resp, ApiErrorId.ERR_LOT_QUALITY_INSUFFICIENT.value)


def test_commit_lot_overcommit_rejected(api):
    """PRD §3.9: "The commit must not push the contract's `committed_quantity` beyond its
    `contracted_quantity`; an overcommit is rejected with `ERR_CONTRACT_OVERCOMMIT`".

    Design: Corner/endpoints/commit_lot_overcommit_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_graded_lot(crop="CORN", quantity=1000.0, grade="GRADE_A")
    contract = create_sale_contract(crop="CORN", contracted_quantity=1000.0, price_per_unit=5.0)
    # commit 1500 against a 1000-contract.
    resp = api.commit_lot(
        contract["id"], {"harvest_lot_id": ctx["lot"]["id"], "commit_quantity": 1500.0}, SA)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_OVERCOMMIT.value)
