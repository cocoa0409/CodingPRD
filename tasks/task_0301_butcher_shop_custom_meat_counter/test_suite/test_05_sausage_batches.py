"""Sausage batches: planned vs actual yield, reserve/cancel revert cascade,
the conserve-lot-grams invariant, and the output-not-grind validation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_cut_type,
    setup_reserved_batch,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
BUTCHER = TEST_USERS["butcher_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc / sausage_batch_planned_vs_actual_yield
# ===========================================================================
def test_batch_planned_vs_actual_yield_diverge(api):
    """PRD §3.8: "The server computes the batch's `actual_yield_g` as the sum of
    its inputs' `weight_g` times one-minus-the-policy's-`shrink_pct_grind`, floored
    to whole grams".

    Inputs 3000+2000=5000, shrink_pct_grind 0.10 -> floor(5000*0.9)=4500; planned
    5000 -> the two diverge.

    Design: Difficulty/dual_variant_calc/sausage_batch_planned_vs_actual_yield
    """
    built = setup_reserved_batch(input_lots=[(3000, 3000), (2000, 2000)],
                                 planned_output_g=5000, recipe_name="Breakfast")
    batch = built["batch"]
    assert batch["planned_output_g"] == 5000
    produced = validate_success(api.produce_batch(batch["id"], BUTCHER))
    assert produced["actual_yield_g"] == 4500, (
        f"actual yield expected 4500, got {produced['actual_yield_g']}"
    )
    assert produced["actual_yield_g"] != produced["planned_output_g"]


def test_batch_produce_creates_output_lot(api):
    """PRD §3.8: "then creates a brand-new `AVAILABLE` `InventoryLot` whose
    `cut_type_id` is the batch's `output_cut_type_id` and whose `received_weight_g`
    is that yield."

    After producing (yield 4500), a new AVAILABLE lot of the grind output cut with
    received_weight_g 4500 exists.

    Design: Difficulty/dual_variant_calc/sausage_batch_planned_vs_actual_yield
    """
    built = setup_reserved_batch(input_lots=[(3000, 3000), (2000, 2000)],
                                 planned_output_g=5000, recipe_name="Breakfast2")
    batch = built["batch"]
    validate_success(api.produce_batch(batch["id"], BUTCHER))
    output_lots = api.list_inventory_lots(
        BUTCHER, params={"cut_type_id": built["output_cut"]["id"]}
    ).json()["data"]
    assert len(output_lots) >= 1
    new_lot = output_lots[-1]
    assert new_lot["received_weight_g"] == 4500
    assert new_lot["lot_status"] == "AVAILABLE"


# ===========================================================================
# Difficulty: transitive_cascade / batch_cancel_reverts_draw_restores_lot
# ===========================================================================
def test_batch_cancel_reverts_draw_restores_depleted_lot(api):
    """PRD §3.8: "Cancelling a `RESERVED` batch compensates the reservation: for
    each `COMMITTED` `LotDraw` of the batch the server sets the draw's
    `draw_status` to `REVERTED`, restores that lot's `remaining_weight_g`,
    increments that lot's `version`, and — if the lot had been `DEPLETED` and now
    has remaining weight above 0 — reverts it `DEPLETED → AVAILABLE`."

    Lot of exactly 2000g fully consumed by reserve (DEPLETED); cancel restores
    remaining to 2000 and reverts DEPLETED -> AVAILABLE.

    Design: Difficulty/transitive_cascade/batch_cancel_reverts_draw_restores_lot
    """
    built = setup_reserved_batch(input_lots=[(2000, 2000)],
                                 planned_output_g=1800, recipe_name="Chorizo")
    batch = built["batch"]
    lot_id = built["lots"][0]["id"]
    depleted = get_success_data(api.get_inventory_lot(lot_id, BUTCHER))
    assert depleted["lot_status"] == "DEPLETED"
    assert depleted["remaining_weight_g"] == 0

    cancelled = validate_success(api.cancel_batch(batch["id"], BUTCHER))
    assert cancelled["batch_status"] == "CANCELLED"
    lot_after = get_success_data(api.get_inventory_lot(lot_id, BUTCHER))
    assert lot_after["remaining_weight_g"] == 2000
    assert lot_after["lot_status"] == "AVAILABLE"


def test_batch_cancel_marks_draw_reverted(api):
    """PRD §3.8: "for each `COMMITTED` `LotDraw` of the batch the server sets the
    draw's `draw_status` to `REVERTED`".
    PRD §3.8: "A `LotDraw` is one of `COMMITTED` or `REVERTED`; a committed draw
    reduces `remaining_weight_g` and a reverted draw restores it."

    After cancel the lot's draw log shows the draw with draw_status REVERTED.

    Design: Difficulty/transitive_cascade/batch_cancel_reverts_draw_restores_lot
    """
    built = setup_reserved_batch(input_lots=[(2000, 2000)],
                                 planned_output_g=1800, recipe_name="Chorizo2")
    batch = built["batch"]
    lot_id = built["lots"][0]["id"]
    validate_success(api.cancel_batch(batch["id"], BUTCHER))
    draws = api.list_lot_draws_for_lot(lot_id, BUTCHER).json()["data"]
    assert len(draws) >= 1
    assert any(d["draw_status"] == "REVERTED" for d in draws), (
        "the committed draw must be marked REVERTED after batch cancel"
    )


# ===========================================================================
# Difficulty: compensating_invariant / batch_reserve_cancel_conserves_lot_remaining_weight
# ===========================================================================
def test_batch_reserve_then_cancel_conserves_lot_grams(api):
    """PRD §3.8: "restores that lot's `remaining_weight_g`, increments that lot's
    `version`".

    Lot 4000g, reserve commits 1500g (remaining 2500); cancel restores remaining
    to 4000 — committed minus reverted nets to zero.

    Design: Difficulty/compensating_invariant/batch_reserve_cancel_conserves_lot_remaining_weight
    """
    built = setup_reserved_batch(input_lots=[(4000, 1500)],
                                 planned_output_g=1350, recipe_name="Bratwurst")
    batch = built["batch"]
    lot_id = built["lots"][0]["id"]
    reserved_lot = get_success_data(api.get_inventory_lot(lot_id, BUTCHER))
    assert reserved_lot["remaining_weight_g"] == 2500

    validate_success(api.cancel_batch(batch["id"], BUTCHER))
    lot_after = get_success_data(api.get_inventory_lot(lot_id, BUTCHER))
    assert lot_after["remaining_weight_g"] == 4000, (
        f"lot grams must be conserved at 4000, got {lot_after['remaining_weight_g']}"
    )
    assert lot_after["lot_status"] == "AVAILABLE"


def test_batch_reserve_reduces_lot_remaining(api):
    """PRD §3.8: "On reserve, for each input the server creates a `COMMITTED`
    `LotDraw` for that input's `weight_g`, reduces that lot's `remaining_weight_g`,
    and increments that lot's `version`".

    Lot 4000g, input 1500g, reserve -> remaining 2500g; this is the forward leg the
    cancel above conserves.

    Design: Difficulty/compensating_invariant/batch_reserve_cancel_conserves_lot_remaining_weight
    """
    built = setup_reserved_batch(input_lots=[(4000, 1500)],
                                 planned_output_g=1350, recipe_name="Bratwurst2")
    lot_id = built["lots"][0]["id"]
    reserved_lot = get_success_data(api.get_inventory_lot(lot_id, BUTCHER))
    assert reserved_lot["remaining_weight_g"] == 2500, (
        f"reserve should reduce remaining to 2500, got {reserved_lot['remaining_weight_g']}"
    )


# ===========================================================================
# Corner: validations / output_not_grind_on_batch_create
# ===========================================================================
def test_batch_output_not_grind_rejected(api):
    """PRD §3.8: "The output cut type must be a grind cut — its `is_grind` must be
    true — or creation is rejected with `ERR_OUTPUT_NOT_GRIND` (HTTP 422)."

    Design: Corner/validations/output_not_grind_on_batch_create
    """
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    resp = api.create_sausage_batch(
        {"recipe_name": "BadBatch", "output_cut_type_id": cut["id"], "planned_output_g": 1000},
        BUTCHER,
    )
    validate_error(resp, ApiErrorId.ERR_OUTPUT_NOT_GRIND.value)
