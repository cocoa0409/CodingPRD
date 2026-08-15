"""Offcut collection and scrap recycling credits: collection gates and the
monthly cumulative volume bonus."""
import pytest

from test_helpers import (
    PLANT,
    ApiErrorId,
    create_approved_spec,
    create_completed_customer_order,
    create_completed_scrap_source,
    create_customer,
    create_locked_cnc_program,
    create_material,
    create_quoted_order,
    create_scrap_batch,
    credit_scrap_batch,
    get_customer,
    process_scrap_batch,
    validate_error,
)


def test_scrap_credit_monthly_tier_boundary(api):
    """PRD §3.7: "The cumulative volume is the sum of `net_recyclable_lb`
    across the batches already in `CREDITED` status whose `credited_at` falls
    within the same UTC calendar month as the current logical clock; credits
    are evaluated sequentially in request-processing order, so each batch's
    tier is judged against only the batches credited strictly before it —
    never by identifier order." PRD §3.7: "When that cumulative volume has
    reached at least 500 pounds — exactly 500 pounds qualifies — the
    effective rate for this batch is the material's
    `scrap_credit_per_lb_cents` multiplied by 1.25; below the threshold the
    base rate applies." PRD §3.7: "The credit posts to the customer of the
    production order's specification: that customer's `credit_balance_cents`
    increases by the batch's `credit_cents`."

    Design: Corner/calculations/scrap_credit_monthly_tier_boundary
    """
    ctx = create_completed_scrap_source(qty=500, method="CNC_ROUTE")
    customer, order = ctx["customer"], ctx["order"]

    b1 = create_scrap_batch(order["id"], 300, 0)
    b2 = create_scrap_batch(order["id"], 200, 0)
    b3 = create_scrap_batch(order["id"], 100, 0)
    assert b1["net_recyclable_lb"] == pytest.approx(300, abs=1e-6)
    for batch in (b1, b2, b3):
        process_scrap_batch(batch["id"])

    c1 = credit_scrap_batch(b1["id"])
    assert c1["credit_cents"] == 3600, "cumulative_before 0: base rate 12"
    c2 = credit_scrap_batch(b2["id"])
    assert c2["credit_cents"] == 2400, "cumulative_before 300 < 500: base rate"
    c3 = credit_scrap_batch(b3["id"])
    assert c3["credit_cents"] == 1500, (
        "cumulative_before exactly 500 qualifies for the 1.25x bonus: 100*15"
    )
    assert get_customer(customer["id"])["credit_balance_cents"] == 7500


def test_scrap_on_non_completed_order_rejected(api):
    """PRD §3.7: "Collecting against an order that is not `COMPLETED` is
    rejected with `ERR_INVALID_STATE` (HTTP 409), and collecting for an order
    whose material is not `recyclable` is rejected with
    `ERR_MATERIAL_NOT_RECYCLABLE` (HTTP 422)."

    Design: Corner/validations/scrap_on_non_completed_order_rejected
    """
    customer, material, spec = create_approved_spec()
    program = create_locked_cnc_program(spec["id"])
    order = create_quoted_order(spec["id"], program["id"], 100)
    assert order["fab_status"] == "QUOTED"

    resp = api.create_scrap_batch(
        {"production_order_id": order["id"], "gross_weight_lb": 50,
         "contamination_pct": 0},
        PLANT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_scrap_on_non_recyclable_material_rejected(api):
    """PRD §3.7: "Collecting against an order that is not `COMPLETED` is
    rejected with `ERR_INVALID_STATE` (HTTP 409), and collecting for an order
    whose material is not `recyclable` is rejected with
    `ERR_MATERIAL_NOT_RECYCLABLE` (HTTP 422)."

    Design: Corner/validations/scrap_on_non_recyclable_material_rejected
    """
    customer = create_customer()
    material = create_material(foam_family="PU", density_pcf=1.8, recyclable=False,
                               scrap_credit_per_lb_cents=0)
    _c, _m, spec = create_approved_spec(customer=customer, material=material)
    program = create_locked_cnc_program(spec["id"])
    order = create_completed_customer_order(spec["id"], program["id"], 100,
                                            machine_id="CNC-1")

    resp = api.create_scrap_batch(
        {"production_order_id": order["id"], "gross_weight_lb": 50,
         "contamination_pct": 0},
        PLANT,
    )
    validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_RECYCLABLE)
