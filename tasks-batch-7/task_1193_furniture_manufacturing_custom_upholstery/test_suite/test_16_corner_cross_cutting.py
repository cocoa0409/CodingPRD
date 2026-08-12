"""Corner tests — §cross_cutting_layers (OCC, FEFO selector determinism)
and §consistency_model (immediate read-after-write)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_line,
    api_client,
    confirm_order,
    create_available_lot,
    create_dealer,
    create_draft_cut_plan,
    create_lot,
    create_model,
    create_order,
    create_spec,
    get_success_data,
    inspect_lot_pass,
    receive_lot,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    validate_error,
    validate_paginated,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]


def test_occ_stale_version_rejected_and_supersede(api):
    """PRD §2.7: "That request must carry `expected_order_line_version`,
    holding the `version` of the order line as the client last observed it.
    If the line's current `version` does not match the supplied value —
    because another writer has advanced the line since the client's last read —
    the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "Creating a new plan supersedes whatever plan the line already
    had — an existing DRAFT or APPROVED plan moves to `SUPERSEDED`, and if the
    superseded plan had been approved, the line's `required_yards_final` is
    cleared back to null — and the create itself increments the line's
    `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_version_rejected_and_supersede
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-OCC", quantity=2, lot_yards=30.0,
    )

    # Capture v1
    line_v1 = validate_success(api.get_order_line(line["id"], PLANNER))
    v1 = line_v1["version"]

    # First create succeeds — supersedes nothing but bumps line version
    plan1 = validate_success(api.create_cut_plan(
        line["id"], {"expected_order_line_version": v1}, PLANNER), 201)
    assert plan1["status"] == "DRAFT"

    # Second create with stale v1 — rejected
    res_stale = api.create_cut_plan(
        line["id"], {"expected_order_line_version": v1}, PLANNER)
    validate_error(res_stale, "ERR_STALE_VERSION", expected_status=412)

    # Fresh version succeeds; first plan superseded
    line_v2 = validate_success(api.get_order_line(line["id"], PLANNER))
    v2 = line_v2["version"]
    assert v2 == v1 + 1
    plan2 = validate_success(api.create_cut_plan(
        line["id"], {"expected_order_line_version": v2}, PLANNER), 201)
    assert plan2["status"] == "DRAFT"

    plan1_now = validate_success(api.get_cut_plan(plan1["id"], PLANNER))
    assert plan1_now["status"] == "SUPERSEDED"

    # Line version advanced again
    line_v3 = validate_success(api.get_order_line(line["id"], PLANNER))
    assert line_v3["version"] == v2 + 1


def test_fefo_selector_order_and_tiebreak(api):
    """PRD §3.3: "For each `PLANT_STOCK` line, the **first-expiry-first-out
    lot selector** walks the eligible pool: material lots matching the line's
    `fabric_spec_id`, with `ownership` `PLANT`, in `AVAILABLE` status, and
    with positive `available_yards`. Eligible lots are ordered by
    `received_at` ascending, ties broken by `created_at` ascending, and the
    selector reserves from each lot the smaller of its `available_yards` and
    the line's remaining requirement, creating ACTIVE allocations as it goes,
    until the requirement is fully covered or the pool is exhausted."

    Design: Corner/cross_cutting_layers/fefo_selector_order_and_tiebreak
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", category="SOFA")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    # Two lots created in sequence; both inspected at the same clock reading,
    # so received_at ties and created_at breaks the tie.
    lot_a = create_lot(spec["id"], expected_yards=6.0)
    receive_lot(lot_a["id"], received_yards=6.0)
    inspect_lot_pass(lot_a["id"], usable_yards=6.0, measured_width_inches=54.0)

    lot_b = create_lot(spec["id"], expected_yards=10.0)
    receive_lot(lot_b["id"], received_yards=10.0)
    inspect_lot_pass(lot_b["id"], usable_yards=10.0, measured_width_inches=54.0)

    order, line = setup_order_with_line(model, spec, dealer,
                                        order_number="ORD-FEFO", quantity=4)
    confirm_order(order["id"])

    # Requirement = 3.0 × 54/52 × 4 × 1.15 = 14.331
    # FEFO: lot A (earlier created_at) drained first to 6.000, then lot B 8.331
    allocs_a, _ = validate_paginated(api.list_material_allocations(
        PLANNER, params={"lot_id": lot_a["id"]}))
    assert len(allocs_a) == 1
    assert allocs_a[0]["yards"] == pytest.approx(6.000, abs=0.001)

    allocs_b, _ = validate_paginated(api.list_material_allocations(
        PLANNER, params={"lot_id": lot_b["id"]}))
    assert len(allocs_b) == 1
    assert allocs_b[0]["yards"] == pytest.approx(8.331, abs=0.001)

    line_now = validate_success(api.get_order_line(line["id"], SALES))
    assert line_now["allocated_yards"] == pytest.approx(14.331, abs=0.001)
    assert line_now["status"] == "ALLOCATED"

    lot_a_now = validate_success(api.get_material_lot(lot_a["id"], RECEIVER))
    assert lot_a_now["available_yards"] == pytest.approx(0.0, abs=0.001)
    lot_b_now = validate_success(api.get_material_lot(lot_b["id"], RECEIVER))
    assert lot_b_now["available_yards"] == pytest.approx(1.669, abs=0.001)


def test_immediate_read_after_write(api):
    """PRD §2.9: "The server keeps this web coherent by transitioning related
    resources automatically whenever criteria are met or violated, without
    waiting for an explicit client request on the affected resource."
    PRD §3.3: "The order's `subtotal_cents` is the sum of the line totals."

    Design: Corner/consistency_model/immediate_read_after_write
    """
    model = create_model(model_code="M-PRICE", category="CHAIR",
                         base_fabric_yards=2.0, base_price_cents=10002,
                         flammability_standard="TB133",
                         option_rules=[{
                             "fabric_grade": "C", "finish_code": "WALNUT",
                             "allowed": True, "surcharge_pct": 0.13,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-C", origin="PLANT", grade="C",
                       nominal_width_inches=54.0, price_per_yard_cents=4000)
    dealer = create_dealer()
    order = create_order("ORD-IMM", dealer["id"])
    add_line(order["id"], model["id"], spec["id"], finish_code="WALNUT", quantity=2)

    # Confirm response itself carries computed totals
    conf = validate_success(api.confirm_order(order["id"], SALES), 200)
    assert conf["subtotal_cents"] == 22604
    assert conf["total_cents"] == 22604
    # No stock — order lands MATERIAL_HOLD
    assert conf["status"] == "MATERIAL_HOLD"

    # Subsequent GET returns identical values — no stale read
    got = validate_success(api.get_customer_order(order["id"], SALES), 200)
    assert got["total_cents"] == 22604
    assert got["subtotal_cents"] == 22604
