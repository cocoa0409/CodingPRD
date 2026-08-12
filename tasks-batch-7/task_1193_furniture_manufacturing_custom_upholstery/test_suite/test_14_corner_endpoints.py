"""Corner tests — §endpoints (error envelope shape, FK reverse reachability,
lot split conservation)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_line,
    api_client,
    book_cell,
    confirm_order,
    create_available_lot,
    create_cell,
    create_certificate,
    create_dealer,
    create_draft_cut_plan,
    create_lot,
    create_model,
    create_order,
    create_shipment_payload,
    create_showroom_sample_payload,
    create_spec,
    get_success_data,
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
SHIP = TEST_USERS["shipping_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_error_envelope_shape_on_forbidden(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format... The `meta` object for error responses contains
    only `api_request_id` and `api_request_timestamp`. The `error_id` is a
    unique, machine-readable string that identifies the specific error."
    PRD §2.1: "A request whose role is valid but not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/endpoints/error_envelope_shape_on_forbidden
    """
    res = api.create_cell({
        "cell_code": "C-X", "cell_type": "CUTTING", "capacity_slots": 1,
        "certifications": [],
    }, SALES)  # SalesRep is not authorized for cell creation
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    body = res.json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"]
    assert "message" in body["data"]
    assert "api_request_id" in body["meta"]


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §4: "List endpoints accept the pagination parameters of §2.3 plus
    resource-specific filters: orders by `dealer_id`; order lines by
    `order_id`, `model_id`, and `fabric_spec_id`; material lots by
    `fabric_spec_id`, `order_line_id`, `parent_lot_id`, and `status`;
    allocations by `lot_id`, `order_line_id`, and `status`; cut plans by
    `order_line_id`; cell bookings by `cell_id`, `order_line_id`, and
    `status`; compliance certificates and shipments by `order_id`; supply
    requisitions by `order_line_id`; and showroom samples by `dealer_id`,
    `model_id`, and `disposition`."

    Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer(sample_allowance_cents=100000)
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-FK", quantity=1, lot_yards=30.0,
    )
    req = get_success_data(api_client.create_supply_requisition({
        "order_line_id": line["id"], "component_code": "FRAME",
        "quantity": 1, "source_type": "DOMESTIC",
    }, PLANNER))
    plan = create_draft_cut_plan(line)
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    booking = book_cell(cell["id"], line["id"], "CUT",
                        "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z")
    sample = get_success_data(api_client.create_showroom_sample(
        create_showroom_sample_payload(
            dealer_id=dealer["id"], model_id=model["id"],
            unit_serial="U-FK", sample_value_cents=10000, due_back_days=30,
        ), SALES))
    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-8", label_count=1)
    ship = get_success_data(api_client.create_shipment(create_shipment_payload(
        order_id=order["id"]), SHIP))

    # Each filtered list returns exactly the one child
    lines, lm = validate_paginated(api.list_order_lines(
        PLANNER, params={"order_id": order["id"]}))
    assert lm["total_count"] == 1 and lines[0]["id"] == line["id"]

    lots, lom = validate_paginated(api.list_material_lots(
        PLANNER, params={"fabric_spec_id": spec["id"]}))
    assert lom["total_count"] == 1 and lots[0]["id"] == lot["id"]

    allocs, am = validate_paginated(api.list_material_allocations(
        PLANNER, params={"lot_id": lot["id"]}))
    assert am["total_count"] == 1
    allocs2, am2 = validate_paginated(api.list_material_allocations(
        PLANNER, params={"order_line_id": line["id"]}))
    assert am2["total_count"] == 1

    plans, pm = validate_paginated(api.list_cut_plans(
        PLANNER, params={"order_line_id": line["id"]}))
    assert pm["total_count"] == 1 and plans[0]["id"] == plan["id"]

    bookings, bm = validate_paginated(api.list_cell_bookings(
        PLANNER, params={"cell_id": cell["id"]}))
    assert bm["total_count"] == 1 and bookings[0]["id"] == booking["id"]

    reqs, rm = validate_paginated(api.list_supply_requisitions(
        PLANNER, params={"order_line_id": line["id"]}))
    assert rm["total_count"] == 1 and reqs[0]["id"] == req["id"]

    samples, sm = validate_paginated(api.list_showroom_samples(
        SALES, params={"dealer_id": dealer["id"]}))
    assert sm["total_count"] == 1 and samples[0]["id"] == sample["id"]

    certs, cm = validate_paginated(api.list_compliance_certificates(
        CO, params={"order_id": order["id"]}))
    assert cm["total_count"] == 1 and certs[0]["id"] == cert["id"]

    ships, shm = validate_paginated(api.list_shipments(
        SHIP, params={"order_id": order["id"]}))
    assert shm["total_count"] == 1 and ships[0]["id"] == ship["id"]

    orders, om = validate_paginated(api.list_customer_orders(
        SALES, params={"dealer_id": dealer["id"]}))
    assert om["total_count"] == 1 and orders[0]["id"] == order["id"]

    # No splits — parent_lot_id filter is empty
    _, plm = validate_paginated(api.list_material_lots(
        PLANNER, params={"parent_lot_id": lot["id"]}))
    assert plm["total_count"] == 0


def test_lot_split_conservation_and_parent_link(api):
    """PRD §3.4: "A receiver may **split** an `AVAILABLE` lot, moving
    `yards_to_move` into a new child lot: the child is created `AVAILABLE`
    with `usable_yards` equal to the moved yards and its `parent_lot_id` set
    to the parent's `id` (a field that is null on every lot not born of a
    split), while the parent's `usable_yards` is decremented by the same
    amount, so the parent's post-split usable plus the child's usable exactly
    equals the parent's pre-split usable. Moving more than the lot's
    `available_yards` is rejected with `ERR_INSUFFICIENT_YARDAGE`..."

    Design: Corner/endpoints/lot_split_conservation_and_parent_link
    """
    spec = create_spec(fabric_code="FAB-A")
    lot = create_available_lot(spec["id"], yards=20.0)

    child = validate_success(api.split_lot(
        lot["id"], {"yards_to_move": 6.5}, RECEIVER), 201)
    assert child["status"] == "AVAILABLE"
    assert child["usable_yards"] == pytest.approx(6.5, abs=0.001)
    assert child["parent_lot_id"] == lot["id"]
    assert child["ownership"] == "PLANT"

    parent = validate_success(api.get_material_lot(lot["id"], RECEIVER))
    assert parent["usable_yards"] == pytest.approx(13.5, abs=0.001)
    # Conservation: 13.5 + 6.5 == 20.0
    assert (parent["usable_yards"] + child["usable_yards"]) == pytest.approx(
        20.0, abs=0.001
    )

    # Second split beyond remaining available fails
    res = api.split_lot(lot["id"], {"yards_to_move": 14.0}, RECEIVER)
    validate_error(res, "ERR_INSUFFICIENT_YARDAGE", expected_status=422)

    # parent_lot_id filter returns exactly the child
    children, cm = validate_paginated(api.list_material_lots(
        RECEIVER, params={"parent_lot_id": lot["id"]}))
    assert cm["total_count"] == 1
    assert children[0]["id"] == child["id"]
