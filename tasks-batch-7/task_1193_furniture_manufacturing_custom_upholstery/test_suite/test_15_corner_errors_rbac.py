"""Corner tests — §errors (per-resource 404s) and §rbac (role denial,
shared reads, segregation of duties)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_line,
    api_client,
    book_cell,
    confirm_order,
    create_cell,
    create_certificate,
    create_dealer,
    create_lot,
    create_model,
    create_order,
    create_spec,
    get_success_data,
    make_compliance_officer_headers,
    make_quality_inspector_headers,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]
QI = TEST_USERS["quality_inspector_headers"]
CO = TEST_USERS["compliance_officer_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


def test_per_resource_not_found_codes(api):
    """PRD §2.8: "Existence and uniqueness — ids referenced in the path and
    body are resolved left to right, and the first missing reference produces
    that resource's 404: `ERR_PRODUCT_MODEL_NOT_FOUND`, `ERR_FABRIC_SPEC_NOT_FOUND`,
    `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
    `ERR_MATERIAL_LOT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_CUT_PLAN_NOT_FOUND`, `ERR_CELL_NOT_FOUND`, `ERR_CELL_BOOKING_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`,
    `ERR_SAMPLE_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND`, each naming the
    resource type whose lookup failed."

    Design: Corner/errors/per_resource_not_found_codes
    """
    cases = [
        ("get_product_model", "ERR_PRODUCT_MODEL_NOT_FOUND"),
        ("get_fabric_spec", "ERR_FABRIC_SPEC_NOT_FOUND"),
        ("get_dealer_account", "ERR_DEALER_NOT_FOUND"),
        ("get_customer_order", "ERR_ORDER_NOT_FOUND"),
        ("get_order_line", "ERR_ORDER_LINE_NOT_FOUND"),
        ("get_material_lot", "ERR_MATERIAL_LOT_NOT_FOUND"),
        ("get_material_allocation", "ERR_ALLOCATION_NOT_FOUND"),
        ("get_cut_plan", "ERR_CUT_PLAN_NOT_FOUND"),
        ("get_cell", "ERR_CELL_NOT_FOUND"),
        ("get_cell_booking", "ERR_CELL_BOOKING_NOT_FOUND"),
        ("get_compliance_certificate", "ERR_CERTIFICATE_NOT_FOUND"),
        ("get_supply_requisition", "ERR_REQUISITION_NOT_FOUND"),
        ("get_showroom_sample", "ERR_SAMPLE_NOT_FOUND"),
        ("get_shipment", "ERR_SHIPMENT_NOT_FOUND"),
    ]
    for method_name, expected_err in cases:
        method = getattr(api, method_name)
        res = method(NON_EXISTENT_UUID, SALES)
        validate_error(res, expected_err, expected_status=404)


def test_rbac_salesrep_cannot_create_cell(api):
    """PRD §2.1: "A request whose role is valid but not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: "POST `/mill/cells` | Create a production cell | ProductionPlanner"

    Design: Corner/rbac/rbac_salesrep_cannot_create_cell
    """
    res = api.create_cell({
        "cell_code": "C-RB", "cell_type": "SEWING", "capacity_slots": 1,
        "certifications": [],
    }, SALES)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    ok = validate_success(api.create_cell({
        "cell_code": "C-RB", "cell_type": "SEWING", "capacity_slots": 1,
        "certifications": [],
    }, PLANNER), 201)
    assert ok["status"] == "ACTIVE"


def test_rbac_qualityinspector_cannot_confirm_order(api):
    """PRD §2.1: "A request whose role is valid but not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: "POST `/mill/customer-orders/{id}/confirm` | Confirm ... | SalesRep"

    Design: Corner/rbac/rbac_qualityinspector_cannot_confirm_order
    """
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-RB2")
    res = api.confirm_order(order["id"], QI)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "DRAFT"


def test_rbac_get_endpoints_shared_all_roles(api):
    """PRD §4: "GET | `/mill/product-models/{id}` | Get a product model | All
    roles |" — the endpoint table assigns every GET endpoint the Authorized
    Role "All roles"; the reads spot-checked here exercise that shared read
    surface.

    Design: Corner/rbac/rbac_get_endpoints_shared_all_roles
    """
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order = create_order("ORD-RB3", dealer["id"])
    lot = create_lot(spec["id"], expected_yards=10.0)

    # Spot-check three roles on three resources — every declared role may read
    validate_success(api.get_product_model(model["id"], RECEIVER), 200)
    validate_success(api.get_customer_order(order["id"], SHIP), 200)
    validate_success(api.get_material_lot(lot["id"], ADMIN), 200)


def test_segregation_of_duties_blocks_inspector_certify(api):
    """PRD §3.7: "Segregation of duties closes the loop: the certifier's
    `X-User-ID` must differ from the `inspected_by` of every lot that has, or
    ever had, an allocation to any line of the order — the inspector who
    passed the fabric may not certify the furniture made from it, and a
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_blocks_inspector_certify
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    # Lot inspected by qi-1
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-SOD", quantity=1, lot_yards=30.0,
        inspector_id="qi-1",
    )
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    b_cut = book_cell(cell["id"], line["id"], "CUT",
                      "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z")
    get_success_data(api_client.start_booking(b_cut["id"], PLANNER))

    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-SOD", label_count=1)

    # Certify as qi-1 (the lot's inspector) — rejected
    res = api.certify_certificate(cert["id"], make_compliance_officer_headers("qi-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)
    cert_now = validate_success(api.get_compliance_certificate(cert["id"], CO))
    assert cert_now["status"] == "DRAFT"

    # Certify as co-2 — succeeds
    ok = validate_success(api.certify_certificate(
        cert["id"], make_compliance_officer_headers("co-2")), 200)
    assert ok["status"] == "CERTIFIED"
    assert ok["certified_by"] == "co-2"
    # certified_at stamped from logical clock
    assert ok["certified_at"].startswith("2026-05-10")
