"""Queue B (breadth) — purchase-order lifecycle: cancellation cascade, the
lines-before-ready guard, the close guard chain, posture gates on spend, and
the line-add gate sequence (brand gate, budget equality/overflow, uniqueness).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    create_procurement_project, create_approved_spec, create_bid,
    create_spec, submit_spec, brand_review,
    sample_decide, award, create_po, add_po_line, transition_po,
    advance_po_to_ready_to_ship, get_po, get_po_line, get_budget_line,
    get_project, create_shipment, transition_shipment,
    attach_po_to_shipment, create_and_post_receiving_event,
    setup_received_pipeline_with_window, run_pipeline,
    create_consolidating_shipment_with_po,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
VEN = TEST_USERS["vendor_headers"]


def test_po_cancel_cascades_lines_and_committed(api):
    """PRD §3.4: "Cancellation by a `PurchasingAgent` is legal from `ISSUED` or
    `ACKNOWLEDGED` and cascades: all non-cancelled lines move to `CANCELLED`,
    `committed_cents` is recomputed for the affected categories and the project,
    and the posture is recomputed."
    PRD §2.10: "Purchase orders that have reached `DELIVERED` or `CLOSED` drop out
    of the committed view; cancelled lines never count."
    Cancelling the ISSUED order drops the category's committed ledger from
    600000c back to zero.

    Design: Corner/state_machines/po_cancel_cascades_lines_and_committed
    """
    scenario = run_pipeline(
        name="P-S12", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 2, "room_count": 20,
            "unit_budget_cents": 15000, "unit_price_cents": 15000,
            "lead_time_days": 14,
            "quantity_ordered": 40, "declared_cube_m3": 10,
        }],
        attach=False, seal=False, depart=False,
    )
    budget_line = scenario["budget_line"]
    assert budget_line["committed_cents"] == 600000

    cancelled = validate_success(
        api_client.transition_purchase_order(
            scenario["po"]["id"],
            {"axis": "FULFILLMENT", "to_status": "CANCELLED"}, PA,
        ),
        200,
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"

    line = get_po_line(scenario["lines"][0]["id"])
    assert line["status"] == "CANCELLED"

    budget_after = get_budget_line(budget_line["id"])
    assert budget_after["committed_cents"] == 0, (
        "cancelled lines drop out of the committed sum"
    )
    project = get_project(scenario["project"]["id"])
    assert project["committed_cents"] == 0
    assert project["procurement_posture"] == "OPEN"


def test_po_ready_requires_lines(api):
    """PRD §3.4: "and later marks it from `ACKNOWLEDGED` to `READY_TO_SHIP`, which
    requires at least one non-cancelled line on the PO (else
    `ERR_PO_HAS_NO_LINES`)."
    An empty acknowledged order cannot advance.

    Design: Corner/state_machines/po_ready_requires_lines
    """
    base = create_procurement_project(
        name="P-S13", total_budget_cents=5_000_000, budgeted_cents=1_000_000,
    )
    po = create_po(base["project"]["id"], "VENDA")
    transition_po(po["id"], "FULFILLMENT", "ACKNOWLEDGED", VEN)

    res = api_client.transition_purchase_order(
        po["id"], {"axis": "FULFILLMENT", "to_status": "READY_TO_SHIP"}, VEN
    )
    validate_error(res, ApiErrorId.ERR_PO_HAS_NO_LINES, expected_status=409)

    assert get_po(po["id"])["fulfillment_status"] == "ACKNOWLEDGED"


def test_po_close_guards_and_double_ack(api):
    """PRD §3.4: "Any fulfillment request that is not legal from the current state
    is rejected with `ERR_INVALID_PO_TRANSITION`."
    PRD §3.4: "A `PurchasingAgent` closes a delivered order — `DELIVERED` to
    `CLOSED` — only when the invoice axis already shows `PAID` (else
    `ERR_INVOICE_NOT_PAID`) and every line is `RECONCILED` or `CANCELLED` (else
    `ERR_LINES_NOT_RECONCILED`)."
    PRD §3.6: "A `PurchasingAgent` may reconcile a line in `FULLY_RECEIVED` or
    `PARTIALLY_RECEIVED` — from any other state the attempt fails with
    `ERR_LINE_NOT_RECEIVED`."
    Full guard chain: double-ack fails; close while INVOICED fails; close after
    PAID but before reconcile fails; after reconcile the close succeeds.

    Design: Corner/endpoints/po_close_guards_and_double_ack
    """
    scenario = run_pipeline(
        name="P-N5", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Lamp", "brand_standard_ref": "MS-L",
            "quantity_per_room": 1, "room_count": 10,
            "unit_budget_cents": 10000, "unit_price_cents": 10000,
            "lead_time_days": 7,
            "quantity_ordered": 10, "declared_cube_m3": 5,
        }],
        attach=False, seal=False, depart=False,
    )
    po_id = scenario["po"]["id"]
    line_id = scenario["lines"][0]["id"]

    transition_po(po_id, "FULFILLMENT", "ACKNOWLEDGED", VEN)
    res = api_client.transition_purchase_order(
        po_id, {"axis": "FULFILLMENT", "to_status": "ACKNOWLEDGED"}, VEN
    )
    validate_error(res, ApiErrorId.ERR_INVALID_PO_TRANSITION,
                   expected_status=409)

    # PO is already ACKNOWLEDGED (the double-ack above was rejected without
    # state change), so step ACKNOWLEDGED -> READY_TO_SHIP directly.
    transition_po(po_id, "FULFILLMENT", "READY_TO_SHIP", VEN)
    shipment = create_consolidating_shipment_with_po(
        scenario["project"]["id"], po_id, "CARR"
    )
    transition_shipment(shipment["id"], "SEALED")
    transition_shipment(shipment["id"], "IN_TRANSIT")
    create_and_post_receiving_event(
        shipment["id"],
        [{"po_line_id": line_id, "qty_received": 10, "qty_damaged": 0}],
    )
    transition_shipment(shipment["id"], "RECEIVED")
    assert get_po(po_id)["fulfillment_status"] == "DELIVERED"

    transition_po(po_id, "INVOICE", "INVOICED", PA)
    res = api_client.transition_purchase_order(
        po_id, {"axis": "FULFILLMENT", "to_status": "CLOSED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_INVOICE_NOT_PAID, expected_status=409)

    transition_po(po_id, "INVOICE", "PAID", PA)
    res = api_client.transition_purchase_order(
        po_id, {"axis": "FULFILLMENT", "to_status": "CLOSED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_LINES_NOT_RECONCILED, expected_status=409)

    validate_success(api_client.reconcile_po_line(line_id, PA), 200)
    closed = validate_success(
        api_client.transition_purchase_order(
            po_id, {"axis": "FULFILLMENT", "to_status": "CLOSED"}, PA
        ),
        200,
    )
    assert closed["fulfillment_status"] == "CLOSED"
    assert closed["invoice_status"] == "PAID"


def test_posture_sealed_blocks_new_po(api):
    """PRD §2.9: "Otherwise, when any installation window of the project is
    `IN_PROGRESS`, the posture is `SEALED`."
    PRD §2.9: "Posture gates new spend: creating a purchase order, adding a line
    to a purchase order, and awarding a bid each require the project's posture to
    be `OPEN`. A `FROZEN` project rejects these with `ERR_PROJECT_BUDGET_FROZEN`;
    a `SEALED` project rejects them with `ERR_PROJECT_PROCUREMENT_SEALED`; when
    both conditions hold, the frozen error is reported first."
    Once the window enters IN_PROGRESS the same purchase-order creation call that
    succeeded earlier is rejected.

    Design: Corner/validations/posture_sealed_blocks_new_po
    """
    scenario = setup_received_pipeline_with_window(
        line_qty=10, line_unit_price=10000, cube=5, received=10,
        floor_number=6, room_number="R-601", room_type="GUEST_KING",
        start_date="2026-07-20", end_date="2026-07-22", crew_count=1,
        task_quantities=(1,), start_window=True,
    )
    project = get_project(scenario["project"]["id"])
    assert project["procurement_posture"] == "SEALED"

    res = api_client.create_purchase_order(
        {"project_id": scenario["project"]["id"], "vendor_name": "VENDA"}, PA
    )
    validate_error(res, ApiErrorId.ERR_PROJECT_PROCUREMENT_SEALED,
                   expected_status=409)


def test_posture_frozen_blocks_line_add(api):
    """PRD §2.9: "The derivation is: when the sum of `committed_cents` and
    `actual_spend_cents` is **strictly greater than** `total_budget_cents`, the
    posture is `FROZEN` — equality with the total budget is *not* frozen."
    PRD §2.9: "Posture gates new spend: creating a purchase order, adding a line
    to a purchase order, and awarding a bid each require the project's posture to
    be `OPEN`. A `FROZEN` project rejects these with `ERR_PROJECT_BUDGET_FROZEN`;
    a `SEALED` project rejects them with `ERR_PROJECT_PROCUREMENT_SEALED`; when
    both conditions hold, the frozen error is reported first."
    Committed 120000c against a 100000c envelope freezes the project, so the next
    line add is rejected even though the category budget line (200000c) has
    headroom.

    Design: Corner/validations/posture_frozen_blocks_line_add
    """
    base = create_procurement_project(
        name="P-V4", total_budget_cents=100000, budgeted_cents=200000,
    )
    project = base["project"]
    spec_1 = create_approved_spec(
        project["id"], category="FURNITURE", description="Bed",
        brand_standard_ref="MS-B", quantity_per_room=1, room_count=2,
        unit_budget_cents=60000,
    )
    bid_1 = create_bid(spec_1["id"], vendor_name="VENDA", unit_price_cents=60000,
                       freight_estimate_cents=0, lead_time_days=7)
    sample_decide(bid_1["id"], "APPROVED")
    award(bid_1["id"])
    spec_2 = create_approved_spec(
        project["id"], category="FURNITURE", description="Hook",
        brand_standard_ref="MS-H", quantity_per_room=1, room_count=1,
        unit_budget_cents=1000,
    )
    bid_2 = create_bid(spec_2["id"], vendor_name="VENDA", unit_price_cents=1000,
                       freight_estimate_cents=0, lead_time_days=3)
    sample_decide(bid_2["id"], "APPROVED")
    award(bid_2["id"])

    po = create_po(project["id"], "VENDA")
    add_po_line(po["id"], spec_1["id"], 2, 4)

    project = get_project(project["id"])
    assert project["committed_cents"] == 120000
    assert project["procurement_posture"] == "FROZEN"

    res = api_client.add_purchase_order_line(
        po["id"],
        {"spec_item_id": spec_2["id"], "quantity_ordered": 1,
         "declared_cube_m3": 1},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_PROJECT_BUDGET_FROZEN,
                   expected_status=409)


def test_line_add_brand_gate_budget_equality_and_overflow(api):
    """PRD §3.4: "The spec must be `BRAND_APPROVED`, else
    `ERR_SPEC_NOT_BRAND_APPROVED`."
    PRD §3.4: "Last in the pipeline comes the fiscal gate: the category's
    `committed_cents` plus the new line's `extended_cents` must remain at or below
    the budget line's `budgeted_cents`; a strictly greater result is rejected with
    `ERR_BUDGET_LINE_EXCEEDED` (402), while landing exactly on the budget is
    allowed."
    PRD §3.4: "At most one non-cancelled line may exist for a spec across all
    purchase orders, else `ERR_SPEC_ALREADY_ORDERED`."
    Four arms on one endpoint: DRAFT spec rejected; a line landing exactly on the
    600000c budget is created; one more cent of commitment overflows; a second
    line on the same spec violates uniqueness.

    Design: Corner/validations/line_add_brand_gate_budget_equality_and_overflow
    """
    base = create_procurement_project(
        name="P-V2", total_budget_cents=10_000_000, budgeted_cents=600000,
    )
    project = base["project"]
    # Arm 1: the spec starts DRAFT; the brand gate rejects the line add.
    spec_1 = create_spec(
        project["id"], category="FURNITURE", description="Guest chair",
        brand_standard_ref="MS-GR-01", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000,
    )
    po = create_po(project["id"], "VENDA")

    res = api_client.add_purchase_order_line(
        po["id"],
        {"spec_item_id": spec_1["id"], "quantity_ordered": 40,
         "declared_cube_m3": 10},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_SPEC_NOT_BRAND_APPROVED,
                   expected_status=409)

    # Arm 2: after submit + brand approval + award, the same line lands exactly
    # on the 600000c budget and is created.
    submit_spec(spec_1["id"])
    brand_review(spec_1["id"], "APPROVE")
    bid_1 = create_bid(spec_1["id"], vendor_name="VENDA", unit_price_cents=15000,
                       freight_estimate_cents=0, lead_time_days=14)
    sample_decide(bid_1["id"], "APPROVED")
    award(bid_1["id"])
    line_1 = validate_success(
        api_client.add_purchase_order_line(
            po["id"],
            {"spec_item_id": spec_1["id"], "quantity_ordered": 40,
             "declared_cube_m3": 10},
            PA,
        ),
        201,
    )
    assert line_1["extended_cents"] == 600000
    assert line_1["unit_price_cents"] == 15000

    # Arm 3: one more line pushes committed above budgeted.
    spec_2 = create_approved_spec(
        project["id"], category="FURNITURE", description="Coat hook",
        brand_standard_ref="MS-CH", quantity_per_room=1, room_count=1,
        unit_budget_cents=1000,
    )
    bid_2 = create_bid(spec_2["id"], vendor_name="VENDA", unit_price_cents=1000,
                       freight_estimate_cents=0, lead_time_days=3)
    sample_decide(bid_2["id"], "APPROVED")
    award(bid_2["id"])
    res = api_client.add_purchase_order_line(
        po["id"],
        {"spec_item_id": spec_2["id"], "quantity_ordered": 1,
         "declared_cube_m3": 1},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_BUDGET_LINE_EXCEEDED, expected_status=402)

    # Arm 4: a second line for the already-ordered spec violates uniqueness.
    res = api_client.add_purchase_order_line(
        po["id"],
        {"spec_item_id": spec_1["id"], "quantity_ordered": 1,
         "declared_cube_m3": 1},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_SPEC_ALREADY_ORDERED, expected_status=409)
