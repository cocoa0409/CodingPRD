"""Thresholds tested exactly on the bound and exactly one step outside it.

The minimum order quantity is inclusive, and the volume discount tier switches
on the very same number, so the accepted boundary case also changes the money.
The sintering QC gate has three independent criteria, each inclusive, so a
failing batch is arranged with every other criterion sitting exactly on its own
bound — only one criterion can then explain the verdict.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_units_conserved,
    assert_no_row_with_code,
    assert_powder_blend_batch,
    assert_total_is_per_unit_times_quantity,
)
from test_helpers.fixtures import APP, MET
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── The minimum order quantity, and the tier that switches with it ──────────

def test_order_quantity_exactly_at_the_minimum_is_accepted_and_prices_on_its_tier(api):
    """25 pieces against a minimum of 25 is admitted and priced at 4678 per unit.

    PRD §3.8: "The `quantity` must be at least the product's `min_order_qty`,
    with equality accepted, otherwise `ERR_BELOW_MIN_ORDER_QTY`;"

    PRD §3.8: "The volume discount is 0.12 when `quantity` is at least 500,
    otherwise 0.07 when it is at least 100, otherwise 0.03 when it is at least
    25, otherwise nothing."

    PRD §3.8: "The gross per-unit price is `list_price_cents` multiplied by the
    quantity one plus the sum of the three surcharge fractions;
    `per_unit_net_cents` is that gross figure multiplied by the quantity one
    minus the volume discount fraction, **rounded half up to whole cents at that
    point**; and `total_price_cents` is `per_unit_net_cents` multiplied by
    `quantity`."

    Design: Difficulty/boundary_precision_check/order_quantity_equals_min_order_qty_passes
    """
    state = fx.draft_order(api, quantity=25, order_overrides={"order_code": "SO-AT-MIN"})

    response = api.submit_tool_order(state["order"]["id"], APP)

    order = validate_success(response)
    assert order["status"] == "SUBMITTED", (
        "a quantity equal to the minimum is admitted, so the order submits, got "
        f"{order['status']}"
    )
    assert order["per_unit_net_cents"] == 4678, (
        "4550 x 1.06 is 4823 gross, and the 25-piece tier's 3 percent discount "
        f"brings that to 4678, got {order['per_unit_net_cents']}"
    )
    assert order["total_price_cents"] == 116950, (
        f"4678 x 25 is 116950, got {order['total_price_cents']}"
    )
    assert_total_is_per_unit_times_quantity(order)
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["open_order_units"] == 25, (
        f"the submitted 25 pieces are now open load, got {product['open_order_units']}"
    )


def test_order_quantity_one_piece_below_the_minimum_is_refused_and_creates_no_row(api):
    """24 pieces against a minimum of 25 is rejected and leaves no order behind.

    PRD §2.11: "31. **Minimum order quantity.** → `ERR_BELOW_MIN_ORDER_QTY`, on
    order creation."

    PRD §3.8: "The `quantity` must be at least the product's `min_order_qty`,
    with equality accepted, otherwise `ERR_BELOW_MIN_ORDER_QTY`;"

    Design: Difficulty/boundary_precision_check/order_quantity_equals_min_order_qty_passes
    """
    state = fx.released_product_with_customer(api)

    response = api.create_tool_order(
        f.tool_order_payload(
            state["customer"]["id"],
            state["product"]["id"],
            fx.current_product_version(api, state["product"]["id"]),
            order_code="SO-BELOW-MIN",
            quantity=24,
        ),
        APP,
    )

    validate_error(response, ApiErrorId.ERR_BELOW_MIN_ORDER_QTY, 422)
    rows, _meta = validate_paginated(api.list_tool_orders(APP))
    assert_no_row_with_code(rows, "order_code", "SO-BELOW-MIN")


# ─── The three sintering QC criteria, each inclusive ─────────────────────────

def _pressed_batch(api, grade_id: str, batch_code: str) -> dict:
    """A batch pressed to exactly 200 green compacts, so the yield denominator is fixed."""
    batch = validate_success(
        api.create_powder_blend_batch(
            f.powder_blend_batch_payload(grade_id, batch_code=batch_code), MET
        ),
        201,
    )
    validate_success(api.press_powder_blend_batch(batch["id"], f.press_payload(), MET))
    return batch


def test_sintering_at_exactly_the_minimum_density_and_a_clear_yield_passes_qc(api):
    """A density of exactly 14.35 with a 90.00 % yield takes the PASSED branch.

    PRD §3.1: "The batch's `qc_status` then moves from `PENDING` to `PASSED`
    when all three of the following hold: `measured_density_gcc` is at least
    14.35; the absolute difference between `measured_hardness_hv` and the
    `hardness_hv` target of the batch's grade, read at the revision the batch
    pinned, is at most 75; and `yield_pct` is at least 85.00. All three
    comparisons are inclusive at the boundary, so a density of exactly 14.35, a
    hardness deviation of exactly 75 and a yield of exactly 85.00 all pass."

    PRD §3.1: "First, `yield_pct` is computed as 100 multiplied by
    `sintered_units` divided by `pressed_units`, rounded half up to two decimal
    places."

    PRD §3.1: "In both outcomes `remaining_units` is set to `sintered_units`."

    Design: Difficulty/boundary_precision_check/sinter_density_and_yield_exactly_at_minimum
    """
    grade = fx.carbide_grade(api)
    batch = _pressed_batch(api, grade["id"], "BLD-A")

    response = api.sinter_powder_blend_batch(
        batch["id"],
        f.sinter_payload(
            sintered_units=180,
            scrap_units=20,
            measured_density_gcc=14.35,
            measured_hardness_hv=1580,
        ),
        MET,
    )

    sintered = validate_success(response)
    assert_powder_blend_batch(sintered)
    assert sintered["yield_pct"] == 90.00, (
        f"100 x 180 / 200 is 90.00, got {sintered['yield_pct']}"
    )
    assert sintered["qc_status"] == "PASSED", (
        "14.35 is inclusive at the density minimum, the hardness sits 20 inside "
        f"tolerance and the yield clears 85.00, got {sintered['qc_status']}"
    )
    assert sintered["stage"] == "SINTERED", (
        f"sintering advances the process dimension, got {sintered['stage']}"
    )
    assert sintered["remaining_units"] == 180, (
        f"the good units out of the furnace are issuable, got {sintered['remaining_units']}"
    )
    assert_batch_units_conserved(sintered)


def test_sintering_one_hundredth_below_the_density_minimum_fails_on_density_alone(api):
    """A density of 14.34 fails even though the yield sits exactly on 85.00.

    PRD §3.1: "If any one of the three fails, `qc_status` moves from `PENDING`
    to `FAILED` instead, and the batch is permanently ineligible as a source of
    trial tools — there is no re-test path out of `FAILED`."

    PRD §3.1: "All three comparisons are inclusive at the boundary, so a density
    of exactly 14.35, a hardness deviation of exactly 75 and a yield of exactly
    85.00 all pass."

    PRD §3.1: "because it both advances `stage` from `PRESSED` to `SINTERED` and
    drives the independent `qc_status` dimension out of `PENDING` in the same
    request."

    Design: Difficulty/boundary_precision_check/sinter_density_and_yield_exactly_at_minimum
    """
    grade = fx.carbide_grade(api)
    batch = _pressed_batch(api, grade["id"], "BLD-B")

    response = api.sinter_powder_blend_batch(
        batch["id"],
        f.sinter_payload(
            sintered_units=170,
            scrap_units=30,
            measured_density_gcc=14.34,
            measured_hardness_hv=1580,
        ),
        MET,
    )

    sintered = validate_success(response)
    assert sintered["yield_pct"] == 85.00, (
        "100 x 170 / 200 is exactly 85.00, which is itself acceptable, got "
        f"{sintered['yield_pct']}"
    )
    assert sintered["qc_status"] == "FAILED", (
        "only the density can explain this verdict: 14.34 is a hundredth under "
        f"the 14.35 minimum, got {sintered['qc_status']}"
    )
    assert sintered["stage"] == "SINTERED", (
        "a QC failure does not roll back the process dimension, got "
        f"{sintered['stage']}"
    )


def test_sintering_at_a_yield_just_under_the_minimum_fails_on_yield_alone(api):
    """A yield of 84.50 fails even though the density sits exactly on 14.35.

    PRD §3.1: "First, `yield_pct` is computed as 100 multiplied by
    `sintered_units` divided by `pressed_units`, rounded half up to two decimal
    places."

    PRD §3.1: "If any one of the three fails, `qc_status` moves from `PENDING`
    to `FAILED` instead, and the batch is permanently ineligible as a source of
    trial tools — there is no re-test path out of `FAILED`."

    PRD §3.1: "A grade never reaches `QUALIFIED` by direct request: that
    transition happens only as a consequence of a dossier approval, as described
    in §3.7."

    Design: Difficulty/boundary_precision_check/sinter_density_and_yield_exactly_at_minimum
    """
    grade = fx.carbide_grade(api)
    batch = _pressed_batch(api, grade["id"], "BLD-C")

    response = api.sinter_powder_blend_batch(
        batch["id"],
        f.sinter_payload(
            sintered_units=169,
            scrap_units=31,
            measured_density_gcc=14.35,
            measured_hardness_hv=1580,
        ),
        MET,
    )

    sintered = validate_success(response)
    assert sintered["yield_pct"] == 84.50, (
        f"100 x 169 / 200 is 84.50, got {sintered['yield_pct']}"
    )
    assert sintered["qc_status"] == "FAILED", (
        "only the yield can explain this verdict: 84.50 is half a point under "
        f"the 85.00 minimum, got {sintered['qc_status']}"
    )
    grade_after = validate_success(api.get_carbide_grade(grade["id"], MET))
    assert grade_after["status"] == "DRAFT", (
        f"sintering alone never promotes the grade, got {grade_after['status']}"
    )
