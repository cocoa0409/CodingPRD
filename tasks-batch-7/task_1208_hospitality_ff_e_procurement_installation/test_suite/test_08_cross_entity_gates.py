"""Queue A (depth) — cross-entity state dependencies: shipment x purchase-order
attach gates, and installation-window x PO-line aggregate stock gating.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    run_pipeline, create_shipment, transition_shipment,
    advance_po_to_ready_to_ship, get_po, get_po_line, get_project,
    setup_received_pipeline_with_window,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
IM = TEST_USERS["installation_manager_headers"]


# ── rule: cross_entity_state_dependency (attach gates) ─────

def _issued_po_and_planned_shipment():
    """PO with one line still ISSUED (never acknowledged); shipment still
    PLANNED (consolidation not opened)."""
    scenario = run_pipeline(
        name="P-XD1", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 2, "room_count": 20,
            "unit_budget_cents": 15000, "unit_price_cents": 15000,
            "lead_time_days": 14,
            "quantity_ordered": 40, "declared_cube_m3": 10,
        }],
        attach=False, seal=False, depart=False,
    )
    shipment = create_shipment(scenario["project"]["id"], "CARR")
    return scenario, shipment


def test_attach_checks_shipment_state_before_po_state(api):
    """PRD §3.5: "a purchase order named by `purchase_order_id` may be attached
    while the shipment is `CONSOLIDATING` — checked first, else
    `ERR_SHIPMENT_NOT_CONSOLIDATING` — and while the PO itself is `READY_TO_SHIP`
    — checked second, else `ERR_PO_NOT_READY_TO_SHIP`"
    With the shipment PLANNED and the PO merely ISSUED, the shipment gate fires
    first.

    Design: Difficulty/cross_entity_state_dependency/attach_requires_shipment_consolidating_and_po_ready
    """
    scenario, shipment = _issued_po_and_planned_shipment()
    po = scenario["po"]

    res = api_client.attach_purchase_order(
        shipment["id"], {"purchase_order_id": po["id"]}, PA
    )
    validate_error(res, ApiErrorId.ERR_SHIPMENT_NOT_CONSOLIDATING,
                   expected_status=409)

    po_after = get_po(po["id"])
    assert po_after["fulfillment_status"] == "ISSUED"
    assert po_after["shipment_id"] is None


def test_attach_requires_po_ready_to_ship_then_succeeds(api):
    """PRD §3.5: "a purchase order named by `purchase_order_id` may be attached
    while the shipment is `CONSOLIDATING` — checked first, else
    `ERR_SHIPMENT_NOT_CONSOLIDATING` — and while the PO itself is `READY_TO_SHIP`
    — checked second, else `ERR_PO_NOT_READY_TO_SHIP`"
    PRD §3.5: "Attachment moves the PO from `READY_TO_SHIP` to `CONSOLIDATED`,
    sets its `shipment_id`, bumps its `version`, and refreshes the shipment's
    `total_cube_m3`."
    Once the shipment is CONSOLIDATING the PO gate reports the ISSUED order;
    after the vendor walks the PO to READY_TO_SHIP the attach succeeds.

    Design: Difficulty/cross_entity_state_dependency/attach_requires_shipment_consolidating_and_po_ready
    """
    scenario, shipment = _issued_po_and_planned_shipment()
    po = scenario["po"]

    transition_shipment(shipment["id"], "CONSOLIDATING")
    res = api_client.attach_purchase_order(
        shipment["id"], {"purchase_order_id": po["id"]}, PA
    )
    validate_error(res, ApiErrorId.ERR_PO_NOT_READY_TO_SHIP, expected_status=409)

    advance_po_to_ready_to_ship(po["id"])
    attached = validate_success(
        api_client.attach_purchase_order(
            shipment["id"], {"purchase_order_id": po["id"]}, PA
        ),
        200,
    )
    assert attached["fulfillment_status"] == "CONSOLIDATED"
    assert attached["shipment_id"] == shipment["id"]

    shipment_after = validate_success(
        api_client.get_shipment(shipment["id"], PA)
    )
    assert shipment_after["total_cube_m3"] == 10


# ── rule: cross_entity_state_dependency (window x line stock) ──

def _window_overdraw_scenario():
    """Line with 10 good units received (qty_installable 10); a RELEASED window
    whose two SCHEDULED tasks draw 10 + 1 = 11 units from that line."""
    return setup_received_pipeline_with_window(
        line_qty=10, line_unit_price=10000, cube=5, received=10,
        floor_number=3, room_number="R-301", room_type="GUEST_KING",
        start_date="2026-07-01", end_date="2026-07-05", crew_count=2,
        task_quantities=(10, 1), start_window=False,
    )


def test_window_start_rejected_when_tasks_overdraw_line_stock(api):
    """PRD §3.7: "Starting work — `RELEASED` to `IN_PROGRESS` — requires at least
    one `SCHEDULED` task on the window (else `ERR_WINDOW_NO_TASKS`) and passes an
    aggregate stock check: for every PO line referenced by the window's scheduled
    tasks, the summed task quantities must not exceed that line's
    `qty_installable`, else `ERR_INSUFFICIENT_INSTALLABLE_STOCK` (409)."
    Tasks totalling 11 units against a 10-unit installable pool block the start.

    Design: Difficulty/cross_entity_state_dependency/window_start_requires_line_stock
    """
    scenario = _window_overdraw_scenario()
    window = scenario["window"]

    res = api_client.transition_installation_window(
        window["id"], {"to_status": "IN_PROGRESS"}, IM
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INSTALLABLE_STOCK,
                   expected_status=409)

    window_after = validate_success(
        api_client.get_installation_window(window["id"], IM)
    )
    assert window_after["status"] == "RELEASED"


def test_rejected_window_start_consumes_no_stock_and_keeps_posture(api):
    """PRD §3.7: "Starting work — `RELEASED` to `IN_PROGRESS` — requires at least
    one `SCHEDULED` task on the window (else `ERR_WINDOW_NO_TASKS`) and passes an
    aggregate stock check: for every PO line referenced by the window's scheduled
    tasks, the summed task quantities must not exceed that line's
    `qty_installable`, else `ERR_INSUFFICIENT_INSTALLABLE_STOCK` (409)."
    PRD §2.9: "Otherwise, when any installation window of the project is
    `IN_PROGRESS`, the posture is `SEALED`."
    The rejected start debits nothing: the line still holds 10 installable, 0
    installed, and — since no window ever entered IN_PROGRESS — the project
    posture remains OPEN.

    Design: Difficulty/cross_entity_state_dependency/window_start_requires_line_stock
    """
    scenario = _window_overdraw_scenario()
    window = scenario["window"]

    res = api_client.transition_installation_window(
        window["id"], {"to_status": "IN_PROGRESS"}, IM
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INSTALLABLE_STOCK,
                   expected_status=409)

    line = get_po_line(scenario["lines"][0]["id"])
    assert line["qty_installable"] == 10
    assert line["qty_installed"] == 0

    project = get_project(scenario["project"]["id"])
    assert project["procurement_posture"] == "OPEN"
