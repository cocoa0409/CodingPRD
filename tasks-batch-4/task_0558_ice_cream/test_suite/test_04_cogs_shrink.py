"""Dual-variant calculations: standard vs actual COGS, allowance vs measured shrink.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    make_flavor, make_size, make_batch,
    open_drawer, open_order, add_line, pay,
    get_order, get_order_line, get_batch,
    api_client, get_success_data,
    TEST_USERS,
)

BAKER = TEST_USERS["baker_headers"]


def _two_cost_batches(flavor_id):
    """Batch A: 90 ml @1.00, expiry 2026-05-10 (FIFO first);
    Batch B: 500 ml @2.00, expiry 2026-05-20."""
    a = make_batch(flavor_id, initial_volume_ml=90, unit_cost_cents_per_ml=1.00,
                   expiry_at="2026-05-10T00:00:00Z")
    b = make_batch(flavor_id, initial_volume_ml=500, unit_cost_cents_per_ml=2.00,
                   expiry_at="2026-05-20T00:00:00Z")
    return a, b


# ─────────────── order_cogs_standard_vs_actual ───────────────

def test_order_cogs_standard_diverges_from_actual(api):
    """PRD 3.4: "the **standard** cost of goods, `standard_cogs_cents`, is `scoops`
    multiplied by 90 ml multiplied by the flavor's `standard_cost_cents_per_ml`,
    rounded half up to whole cents".
    PRD 3.4: "The **actual** cost of goods, `actual_cogs_cents`, is the sum over
    that line's `allocations` of each draw's `volume_ml` multiplied by that draw's
    `unit_cost_cents_per_ml`, rounded half up to whole cents".
    PRD 3.4: "The order's `standard_cogs_cents` and `actual_cogs_cents` are the sums
    of the respective line figures".

    Design: Difficulty/dual_variant_calc/order_cogs_standard_vs_actual
    """
    flavor = make_flavor(name="Vanilla", allergens=["MILK", "EGG"],
                         standard_cost_cents_per_ml=1.80, par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    _two_cost_batches(flavor["id"])
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"])
    pay(order["id"], payment_method="CARD")
    line_after = get_order_line(line["id"])
    order_after = get_order(order["id"])
    # standard: round(180 * 1.80) = 324; actual: 90*1.00 + 90*2.00 = 270.
    assert line_after["standard_cogs_cents"] == 324
    assert line_after["actual_cogs_cents"] == 270
    assert order_after["standard_cogs_cents"] == 324
    assert order_after["actual_cogs_cents"] == 270


def test_order_cogs_fifo_allocations_composition(api):
    """PRD 3.3: "The line records its per-batch draws in `allocations`, an array of
    entries each carrying a `batch_id`, the drawn `volume_ml`, and that batch's
    `unit_cost_cents_per_ml`."
    PRD 3.3: "Candidates are consumed in order of `expiry_at` ascending — earliest
    expiry first — with ties broken by `created_at` ascending".

    Design: Difficulty/dual_variant_calc/order_cogs_standard_vs_actual
    """
    flavor = make_flavor(name="Vanilla", standard_cost_cents_per_ml=1.80, par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    a, b = _two_cost_batches(flavor["id"])
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"])
    line = get_order_line(line["id"])
    allocs = line["allocations"]
    assert len(allocs) == 2, f"expected two FIFO draws, got {allocs}"
    # Earliest expiry (Batch A) drawn first, up to its 90 ml headroom, then Batch B.
    assert allocs[0]["batch_id"] == a["id"]
    assert allocs[0]["volume_ml"] == 90
    assert allocs[0]["unit_cost_cents_per_ml"] == 1.00
    assert allocs[1]["batch_id"] == b["id"]
    assert allocs[1]["volume_ml"] == 90
    assert allocs[1]["unit_cost_cents_per_ml"] == 2.00


# ─────────────── batch_shrink_allowance_vs_measured ───────────────

def test_batch_shrink_allowance_diverges_from_measured(api):
    """PRD 3.2: "The **allowance** figure, `expected_shrink_ml`, is the planned
    shrink budget: it is `initial_volume_ml` multiplied by the shrink allowance of
    five percent (0.05), rounded half up to a whole milliliter."
    PRD 3.2: "The **measured** figure, `actual_shrink_ml`, is the real observed
    loss: it is the sum of the `volume_ml` of every waste event on the batch whose
    `waste_type` is one of `MELT`, `SPILLAGE`, or `TRIM_SHRINK`".
    PRD 3.2: "The `shrink_variance_ml` is the measured figure minus the expected
    figure (`actual_shrink_ml` minus `expected_shrink_ml`)".

    Design: Difficulty/dual_variant_calc/batch_shrink_allowance_vs_measured
    """
    flavor = make_flavor(name="Vanilla", standard_cost_cents_per_ml=1.50, par_level_ml=500)
    batch = make_batch(flavor["id"], initial_volume_ml=1000, unit_cost_cents_per_ml=1.50,
                       expiry_at="2026-05-30T00:00:00Z")
    get_success_data(api.create_waste_event({"batch_id": batch["id"], "waste_type": "MELT", "volume_ml": 30}, BAKER))
    get_success_data(api.create_waste_event({"batch_id": batch["id"], "waste_type": "SPILLAGE", "volume_ml": 40}, BAKER))
    b = get_batch(batch["id"])
    assert b["wasted_volume_ml"] == 70
    assert b["remaining_volume_ml"] == 930
    assert b["expected_shrink_ml"] == 50    # round_half_up(1000*0.05)
    assert b["actual_shrink_ml"] == 70      # 30 + 40
    assert b["shrink_variance_ml"] == 20    # 70 - 50


def test_batch_expected_shrink_rounds_half_up(api):
    """PRD 3.2: "it is `initial_volume_ml` multiplied by the shrink allowance of
    five percent (0.05), rounded half up to a whole milliliter."

    Design: Difficulty/dual_variant_calc/batch_shrink_allowance_vs_measured
    """
    flavor = make_flavor(name="Vanilla", standard_cost_cents_per_ml=1.50, par_level_ml=500)
    batch = make_batch(flavor["id"], initial_volume_ml=990, unit_cost_cents_per_ml=1.50,
                       expiry_at="2026-05-30T00:00:00Z")
    get_success_data(api.create_waste_event({"batch_id": batch["id"], "waste_type": "MELT", "volume_ml": 100}, BAKER))
    b = get_batch(batch["id"])
    # 990 * 0.05 = 49.5 -> round half up -> 50
    assert b["expected_shrink_ml"] == 50
    assert b["actual_shrink_ml"] == 100
    assert b["shrink_variance_ml"] == 50
