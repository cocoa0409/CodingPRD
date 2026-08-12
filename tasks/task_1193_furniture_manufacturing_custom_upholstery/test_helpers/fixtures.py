"""Composite setup helpers for multi-step test prerequisites.

Fixtures use get_success_data() (lenient validator) so setup failures
surface as clear setup errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_TEST_ISO
from .factories import (
    create_cell_booking_payload,
    create_cell_payload,
    create_compliance_certificate_payload,
    create_customer_order_payload,
    create_dealer_account_payload,
    create_fabric_spec_payload,
    create_material_lot_payload,
    create_order_line_payload,
    create_product_model_payload,
    create_shipment_payload,
    create_showroom_sample_payload,
    create_supply_requisition_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_plant_admin_headers,
    make_production_planner_headers,
    make_quality_inspector_headers,
    make_sales_rep_headers,
    make_shipping_coordinator_headers,
)

# Aliases used throughout fixtures
SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]
QI = TEST_USERS["quality_inspector_headers"]
CO = TEST_USERS["compliance_officer_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


# ─── Tier 1: state and entity primitives ─────────────────────────────


def set_clock(iso: str = CLOCK_TEST_ISO):
    """Drive the server's logical clock to a known instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def create_model(model_code: str = "M-NP", base_price_cents: int = 50000,
                 base_fabric_yards: float = 3.0, requires_pattern_match: bool = False,
                 flammability_standard: str = "TB117_2013",
                 required_component_codes=None, option_rules=None,
                 category: str = "CHAIR"):
    """Create a ProductModel. Defaults: no pattern match, grade-A ANY-allowed rule."""
    if option_rules is None:
        option_rules = [
            {
                "fabric_grade": "A",
                "finish_code": "ANY",
                "allowed": True,
                "surcharge_pct": 0.0,
                "lead_time_adder_days": 0,
            }
        ]
    if required_component_codes is None:
        required_component_codes = []
    payload = create_product_model_payload(
        model_code=model_code,
        category=category,
        base_fabric_yards=base_fabric_yards,
        base_price_cents=base_price_cents,
        requires_pattern_match=requires_pattern_match,
        flammability_standard=flammability_standard,
        required_component_codes=required_component_codes,
        option_rules=option_rules,
    )
    return get_success_data(api_client.create_product_model(payload, PLANNER))


def create_spec(fabric_code: str = "FAB-A", origin: str = "PLANT", grade: str = "A",
                nominal_width_inches: float = 54.0,
                pattern_repeat_v_inches=None, pattern_repeat_h_inches=None,
                match_method=None, price_per_yard_cents=None,
                com_credit_per_yard_cents=None):
    """Create a FabricSpec."""
    kwargs = {
        "fabric_code": fabric_code,
        "origin": origin,
        "grade": grade,
        "nominal_width_inches": nominal_width_inches,
    }
    if pattern_repeat_v_inches is not None:
        kwargs["pattern_repeat_v_inches"] = pattern_repeat_v_inches
    if pattern_repeat_h_inches is not None:
        kwargs["pattern_repeat_h_inches"] = pattern_repeat_h_inches
    if match_method is not None:
        kwargs["match_method"] = match_method
    if price_per_yard_cents is not None:
        kwargs["price_per_yard_cents"] = price_per_yard_cents
    if com_credit_per_yard_cents is not None:
        kwargs["com_credit_per_yard_cents"] = com_credit_per_yard_cents
    payload = create_fabric_spec_payload(**kwargs)
    return get_success_data(api_client.create_fabric_spec(payload, PLANNER))


def create_dealer(dealer_code: str = "DLR-001", credit_limit_cents: int = 100000000,
                  sample_allowance_cents: int = 5000000, name: str = "Blue Ridge Furniture"):
    """Create a DealerAccount."""
    payload = create_dealer_account_payload(
        dealer_code=dealer_code, name=name,
        credit_limit_cents=credit_limit_cents,
        sample_allowance_cents=sample_allowance_cents,
    )
    return get_success_data(api_client.create_dealer_account(payload, SALES))


def create_order(order_number: str, dealer_id: str,
                 ship_to_state: str = "NC", delivery_method: str = "LTL_FREIGHT"):
    """Create a DRAFT CustomerOrder."""
    payload = create_customer_order_payload(
        order_number=order_number, dealer_id=dealer_id,
        ship_to_state=ship_to_state, delivery_method=delivery_method,
    )
    return get_success_data(api_client.create_customer_order(payload, SALES))


def add_line(order_id: str, model_id: str, fabric_spec_id: str,
             fabric_source: str = "PLANT_STOCK", finish_code: str = "ESPRESSO",
             quantity: int = 1):
    """Add an OrderLine to a DRAFT order."""
    payload = create_order_line_payload(
        order_id=order_id, model_id=model_id, fabric_spec_id=fabric_spec_id,
        fabric_source=fabric_source, finish_code=finish_code, quantity=quantity,
    )
    return get_success_data(api_client.create_order_line(payload, SALES))


def confirm_order(order_id: str):
    """Confirm an order. Returns the updated CustomerOrder."""
    return get_success_data(api_client.confirm_order(order_id, SALES))


def create_lot(fabric_spec_id: str, expected_yards: float = 30.0,
               order_line_id=None):
    """Register an EXPECTED MaterialLot."""
    kwargs = {"fabric_spec_id": fabric_spec_id, "expected_yards": expected_yards}
    if order_line_id is not None:
        kwargs["order_line_id"] = order_line_id
    return get_success_data(api_client.create_material_lot(
        create_material_lot_payload(**kwargs), RECEIVER))


def receive_lot(lot_id: str, received_yards: float):
    """Receive an EXPECTED lot."""
    return get_success_data(api_client.receive_lot(
        lot_id, {"received_yards": received_yards}, RECEIVER))


def inspect_lot_pass(lot_id: str, usable_yards: float, rejected_yards: float = 0.0,
                     measured_width_inches: float = 54.0, inspector_id: str = "qi-1"):
    """Inspect a RECEIVED lot with result PASS. Returns the AVAILABLE lot."""
    headers = make_quality_inspector_headers(inspector_id)
    return get_success_data(api_client.inspect_lot(lot_id, {
        "result": "PASS",
        "usable_yards": usable_yards,
        "rejected_yards": rejected_yards,
        "measured_width_inches": measured_width_inches,
    }, headers))


def inspect_lot_fail(lot_id: str, received_yards: float, inspector_id: str = "qi-1"):
    """Inspect a RECEIVED lot with result FAIL."""
    headers = make_quality_inspector_headers(inspector_id)
    return get_success_data(api_client.inspect_lot(lot_id, {
        "result": "FAIL",
        "usable_yards": 0.0,
        "rejected_yards": received_yards,
    }, headers))


def create_available_lot(fabric_spec_id: str, yards: float = 30.0,
                         measured_width_inches: float = 54.0,
                         inspector_id: str = "qi-1"):
    """Create + receive + inspect PASS a lot, returning the AVAILABLE lot."""
    lot = create_lot(fabric_spec_id, expected_yards=yards)
    receive_lot(lot["id"], received_yards=yards)
    return inspect_lot_pass(lot["id"], usable_yards=yards,
                            measured_width_inches=measured_width_inches,
                            inspector_id=inspector_id)


def create_cell(cell_code: str = "C-CUT", cell_type: str = "CUTTING",
                capacity_slots: int = 1, certifications=None):
    """Create a Cell."""
    payload = create_cell_payload(
        cell_code=cell_code, cell_type=cell_type,
        capacity_slots=capacity_slots,
        certifications=certifications or [],
    )
    return get_success_data(api_client.create_cell(payload, PLANNER))


def book_cell(cell_id: str, order_line_id: str, operation: str,
              start_at: str, end_at: str):
    """Create a CellBooking."""
    payload = create_cell_booking_payload(
        cell_id=cell_id, order_line_id=order_line_id, operation=operation,
        start_at=start_at, end_at=end_at,
    )
    return get_success_data(api_client.create_cell_booking(payload, PLANNER))


def start_and_complete_booking(booking_id: str):
    """Start then complete a CellBooking. Returns the COMPLETED booking."""
    get_success_data(api_client.start_booking(booking_id, PLANNER))
    return get_success_data(api_client.complete_booking(booking_id, PLANNER))


def create_certificate(order_id: str, standard: str = "TB117_2013",
                       label_lot_number: str = "LBL-1", label_count: int = 1):
    """Create a DRAFT ComplianceCertificate."""
    payload = create_compliance_certificate_payload(
        order_id=order_id, standard=standard,
        label_lot_number=label_lot_number, label_count=label_count,
    )
    return get_success_data(api_client.create_compliance_certificate(payload, CO))


# ─── Tier 2: composite setups ────────────────────────────────────────


def setup_basic_context(model_code="M-NP", fabric_code="FAB-A",
                        base_fabric_yards=3.0, base_price_cents=50000,
                        requires_pattern_match=False, option_rules=None,
                        required_component_codes=None,
                        pattern_repeat_v_inches=None, match_method=None,
                        origin="PLANT", grade="A",
                        com_credit_per_yard_cents=None,
                        credit_limit_cents=100000000,
                        sample_allowance_cents=5000000,
                        flammability_standard="TB117_2013",
                        clock_iso=CLOCK_TEST_ISO):
    """Clock + model + spec + dealer. Returns (model, spec, dealer)."""
    set_clock(clock_iso)
    model = create_model(
        model_code=model_code,
        base_price_cents=base_price_cents,
        base_fabric_yards=base_fabric_yards,
        requires_pattern_match=requires_pattern_match,
        flammability_standard=flammability_standard,
        required_component_codes=required_component_codes,
        option_rules=option_rules,
    )
    spec = create_spec(
        fabric_code=fabric_code, origin=origin, grade=grade,
        pattern_repeat_v_inches=pattern_repeat_v_inches,
        match_method=match_method,
        com_credit_per_yard_cents=com_credit_per_yard_cents,
    )
    dealer = create_dealer(credit_limit_cents=credit_limit_cents,
                           sample_allowance_cents=sample_allowance_cents)
    return model, spec, dealer


def setup_order_with_line(model, spec, dealer,
                          order_number="ORD-1", quantity=1,
                          fabric_source="PLANT_STOCK",
                          finish_code="ESPRESSO",
                          delivery_method="LTL_FREIGHT"):
    """Create DRAFT order + one line. Returns (order, line)."""
    order = create_order(order_number, dealer["id"], delivery_method=delivery_method)
    line = add_line(order["id"], model["id"], spec["id"],
                    fabric_source=fabric_source,
                    finish_code=finish_code, quantity=quantity)
    return order, line


def setup_confirmed_order_with_plant_stock(model, spec, dealer,
                                            order_number="ORD-1", quantity=1,
                                            lot_yards=30.0,
                                            lot_measured_width_inches=54.0,
                                            inspector_id="qi-1"):
    """Plant-stock line confirmed against a pre-existing AVAILABLE lot.
    Returns (order, line, lot)."""
    lot = create_available_lot(
        spec["id"], yards=lot_yards,
        measured_width_inches=lot_measured_width_inches,
        inspector_id=inspector_id,
    )
    order, line = setup_order_with_line(
        model, spec, dealer, order_number=order_number, quantity=quantity,
    )
    confirm_order(order["id"])
    order = get_success_data(api_client.get_customer_order(order["id"], SALES))
    line = get_success_data(api_client.get_order_line(line["id"], SALES))
    lot = get_success_data(api_client.get_material_lot(lot["id"], RECEIVER))
    return order, line, lot


def setup_confirmed_com_order(model, spec, dealer,
                              order_number="ORD-COM", quantity=1):
    """COM line confirmed (no lot yet) -> order MATERIAL_HOLD, line MATERIAL_SHORTFALL.
    Returns (order, line)."""
    order, line = setup_order_with_line(
        model, spec, dealer, order_number=order_number, quantity=quantity,
        fabric_source="COM",
    )
    confirm_order(order["id"])
    order = get_success_data(api_client.get_customer_order(order["id"], SALES))
    line = get_success_data(api_client.get_order_line(line["id"], SALES))
    return order, line


def resolve_com_line_with_lot(line, spec, usable_yards, measured_width_inches=54.0,
                              expected_yards=None, inspector_id="qi-1"):
    """Register/receive/inspect-PASS a COM lot bound to `line` so the line
    picks up its auto-allocation. Returns the AVAILABLE lot."""
    if expected_yards is None:
        expected_yards = usable_yards
    lot = create_lot(spec["id"], expected_yards=expected_yards,
                     order_line_id=line["id"])
    receive_lot(lot["id"], received_yards=expected_yards)
    return inspect_lot_pass(lot["id"], usable_yards=usable_yards,
                            measured_width_inches=measured_width_inches,
                            inspector_id=inspector_id)


def create_draft_cut_plan(line):
    """Create a DRAFT CutPlan against `line` (OCC-checked). Returns the plan."""
    line_now = get_success_data(api_client.get_order_line(line["id"], PLANNER))
    return get_success_data(api_client.create_cut_plan(
        line["id"], {"expected_order_line_version": line_now["version"]}, PLANNER))


def create_approved_cut_plan(line, marker_length_yards):
    """Create + approve a CutPlan. Returns the APPROVED plan."""
    plan = create_draft_cut_plan(line)
    return get_success_data(api_client.approve_cut_plan(
        plan["id"], {"marker_length_yards": marker_length_yards}, PLANNER))


def record_cut_on_plan(plan):
    """Run record-cut. Returns the CUT plan."""
    return get_success_data(api_client.record_cut(plan["id"], PLANNER))


def create_completed_cut_booking(cell, line,
                                 start_at="2026-06-01T08:00:00Z",
                                 end_at="2026-06-01T09:00:00Z"):
    """Create + start + complete a CUT booking. Returns the COMPLETED booking."""
    booking = book_cell(cell["id"], line["id"], "CUT", start_at, end_at)
    return start_and_complete_booking(booking["id"])


def setup_three_cells(certifications=None):
    """Create CUTTING + SEWING + UPHOLSTERY cells. Returns (cut, sew, uph)."""
    certifications = certifications or []
    c_cut = create_cell("C-CUT", "CUTTING", 1, certifications)
    c_sew = create_cell("C-SEW", "SEWING", 1, certifications)
    c_uph = create_cell("C-UPH", "UPHOLSTERY", 1, certifications)
    return c_cut, c_sew, c_uph


def drive_line_through_production(line, c_cut, c_sew, c_uph,
                                  marker_length_yards=3.5,
                                  base_date="2026-06-01"):
    """Drive an ALLOCATED line to UPHOLSTERED.

    Steps: CUT booking (start+complete), create+approve cut plan, record-cut,
    SEW booking (start+complete), UPHOLSTER booking (start+complete).
    Returns nothing; reads should be done by the caller.
    """
    b_cut = book_cell(c_cut["id"], line["id"], "CUT",
                      f"{base_date}T08:00:00Z", f"{base_date}T09:00:00Z")
    start_and_complete_booking(b_cut["id"])
    plan = create_approved_cut_plan(line, marker_length_yards)
    record_cut_on_plan(plan)
    b_sew = book_cell(c_sew["id"], line["id"], "SEW",
                      f"{base_date}T09:00:00Z", f"{base_date}T10:00:00Z")
    start_and_complete_booking(b_sew["id"])
    b_uph = book_cell(c_uph["id"], line["id"], "UPHOLSTER",
                      f"{base_date}T10:00:00Z", f"{base_date}T11:00:00Z")
    start_and_complete_booking(b_uph["id"])


def setup_order_in_quality_review(model, spec, dealer,
                                   order_number="ORD-QR", quantity=1,
                                   marker_length_yards=3.5,
                                   lot_yards=30.0):
    """Plant-stock confirmed order driven through production to QUALITY_REVIEW.
    Returns (order, line, lot, (c_cut, c_sew, c_uph))."""
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number=order_number, quantity=quantity,
        lot_yards=lot_yards,
    )
    cells = setup_three_cells()
    drive_line_through_production(line, *cells, marker_length_yards=marker_length_yards)
    order = get_success_data(api_client.get_customer_order(order["id"], SALES))
    line = get_success_data(api_client.get_order_line(line["id"], SALES))
    return order, line, lot, cells


def setup_order_ready_to_ship(model, spec, dealer,
                               order_number="ORD-RTS", quantity=1,
                               marker_length_yards=3.5,
                               certifier_id="co-2",
                               pass_qi_id="qi-1"):
    """Order driven to READY_TO_SHIP (certificate created + CERTIFIED,
    pass-quality called). Returns (order, line, lot, cells, cert)."""
    order, line, lot, cells = setup_order_in_quality_review(
        model, spec, dealer, order_number=order_number, quantity=quantity,
        marker_length_yards=marker_length_yards,
    )
    total_qty = line["quantity"]
    cert = create_certificate(order["id"], standard=model["flammability_standard"],
                              label_lot_number="LBL-1", label_count=total_qty)
    cert = get_success_data(api_client.certify_certificate(
        cert["id"], make_compliance_officer_headers(certifier_id)))
    get_success_data(api_client.pass_quality(
        order["id"], make_quality_inspector_headers(pass_qi_id)))
    order = get_success_data(api_client.get_customer_order(order["id"], SALES))
    return order, line, lot, cells, cert


def setup_delivered_shipment(model, spec, dealer, order_number="ORD-DL",
                              quantity=1, marker_length_yards=3.5,
                              delivery_method="LTL_FREIGHT"):
    """Order + shipment fully delivered. Returns (order, line, lot, cells, cert, shipment)."""
    order, line, lot, cells, cert = setup_order_ready_to_ship(
        model, spec, dealer, order_number=order_number, quantity=quantity,
        marker_length_yards=marker_length_yards,
    )
    ship = get_success_data(api_client.create_shipment(
        create_shipment_payload(order_id=order["id"]), SHIP))
    get_success_data(api_client.rate_shipment(ship["id"], SHIP))
    get_success_data(api_client.tender_shipment(ship["id"], SHIP))
    pickup_payload = {}
    if delivery_method == "WHITE_GLOVE":
        pickup_payload = {"condition_check_passed": True}
    get_success_data(api_client.record_pickup(ship["id"], pickup_payload, SHIP))
    get_success_data(api_client.record_delivery(ship["id"], SHIP))
    ship = get_success_data(api_client.get_shipment(ship["id"], SHIP))
    order = get_success_data(api_client.get_customer_order(order["id"], SALES))
    return order, line, lot, cells, cert, ship
