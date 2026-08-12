"""Corner tests — §validations (priority ordering, business violations,
temporal gates, fiscal gates, RBAC cross-checks)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_line,
    api_client,
    book_cell,
    build_user_headers,
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
    inspect_lot_fail,
    inspect_lot_pass,
    make_compliance_officer_headers,
    make_quality_inspector_headers,
    receive_lot,
    set_clock,
    setup_confirmed_com_order,
    setup_confirmed_order_with_plant_stock,
    setup_order_in_quality_review,
    setup_order_with_line,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_auth_missing_header_beats_state_check(api):
    """PRD §2.8: "1. **Authentication context** — `X-User-ID` and `X-User-Role`
    present and the role declared; failures yield
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This guard applies
    to every endpoint."
    PRD §2.8: "the server evaluates them in a fixed order so the surfaced
    error is deterministic."

    Design: Corner/validations/auth_missing_header_beats_state_check
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-A1")
    confirm_order(order["id"])
    # Confirm again (order not DRAFT) with an undeclared role — auth wins
    res = api.confirm_order(order["id"], build_user_headers("x-1", "NotARole"))
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_option_combo_restricted_rejected(api):
    """PRD §3.1: "If no row matches, or the matching row is not allowed, the
    combination is rejected with `ERR_OPTION_COMBO_RESTRICTED`."

    Design: Corner/validations/option_combo_restricted_rejected
    """
    model = create_model(
        model_code="M-RESTR",
        option_rules=[{
            "fabric_grade": "D", "finish_code": "ESPRESSO",
            "allowed": False, "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-D", origin="PLANT", grade="D",
                       nominal_width_inches=54.0, price_per_yard_cents=5000)
    dealer = create_dealer()
    order = create_order("ORD-RESTR", dealer["id"])

    res = api.create_order_line({
        "order_id": order["id"], "model_id": model["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "ESPRESSO", "quantity": 1,
    }, SALES)
    validate_error(res, "ERR_OPTION_COMBO_RESTRICTED", expected_status=422)


def test_option_matrix_exact_beats_any(api):
    """PRD §3.1: "When a line is priced against the matrix, an exact row — one
    matching both the line's fabric grade and its finish code — beats the
    wildcard row; when only the wildcard matches, it governs."

    Design: Corner/validations/option_matrix_exact_beats_any
    """
    model = create_model(
        model_code="M-MATRIX", category="SOFA", base_price_cents=20000,
        option_rules=[
            {"fabric_grade": "A", "finish_code": "ESPRESSO", "allowed": True,
             "surcharge_pct": 0.25, "lead_time_adder_days": 0},
            {"fabric_grade": "A", "finish_code": "ANY", "allowed": True,
             "surcharge_pct": 0.10, "lead_time_adder_days": 0},
        ],
    )
    spec = create_spec(fabric_code="FAB-A", origin="PLANT", grade="A",
                       nominal_width_inches=54.0, price_per_yard_cents=3000)
    dealer = create_dealer()
    order = create_order("ORD-MAT", dealer["id"])

    line_e = validate_success(api.create_order_line({
        "order_id": order["id"], "model_id": model["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "ESPRESSO", "quantity": 1,
    }, SALES), 201)
    # exact row wins: 20000 × 1.25 = 25000
    assert line_e["matched_surcharge_pct"] == pytest.approx(0.25, abs=0.0001)
    assert line_e["unit_price_cents"] == 25000

    line_w = validate_success(api.create_order_line({
        "order_id": order["id"], "model_id": model["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "WALNUT", "quantity": 1,
    }, SALES), 201)
    # falls through to ANY: 20000 × 1.10 = 22000
    assert line_w["matched_surcharge_pct"] == pytest.approx(0.10, abs=0.0001)
    assert line_w["unit_price_cents"] == 22000


def test_mixed_flammability_standards_rejected(api):
    """PRD §3.2: "the first line added to an order sets the order's read-only
    `common_flammability_standard` to that line's model standard, and every
    later line must carry a model with the same standard or be rejected with
    `ERR_FLAMMABILITY_STANDARD_MISMATCH`."

    Design: Corner/validations/mixed_flammability_standards_rejected
    """
    opt = [{"fabric_grade": "A", "finish_code": "ANY", "allowed": True,
            "surcharge_pct": 0.0, "lead_time_adder_days": 0}]
    m_tb = create_model(model_code="M-TB", flammability_standard="TB117_2013",
                        option_rules=opt)
    m_uf = create_model(model_code="M-UF", flammability_standard="UFAC",
                        option_rules=opt)
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order = create_order("ORD-MIX", dealer["id"], ship_to_state="CA")
    add_line(order["id"], m_tb["id"], spec["id"])

    res = api.create_order_line({
        "order_id": order["id"], "model_id": m_uf["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "ESPRESSO", "quantity": 1,
    }, SALES)
    validate_error(res, "ERR_FLAMMABILITY_STANDARD_MISMATCH", expected_status=422)
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["common_flammability_standard"] == "TB117_2013"


def test_label_count_mismatch_rejected(api):
    """PRD §3.7: "the `label_count` must equal the summed `quantity` of the
    order's lines (else `ERR_LABEL_COUNT_MISMATCH`)."

    Design: Corner/validations/label_count_mismatch_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-LBL", quantity=2, lot_yards=30.0,
    )
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    b_cut = book_cell(cell["id"], line["id"], "CUT",
                      "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z")
    get_success_data(api_client.start_booking(b_cut["id"], PLANNER))
    # Order is now IN_PRODUCTION; total quantity across lines = 2
    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-5", label_count=99)
    res = api.certify_certificate(cert["id"], make_compliance_officer_headers("co-2"))
    validate_error(res, "ERR_LABEL_COUNT_MISMATCH", expected_status=422)
    cert_now = validate_success(api.get_compliance_certificate(cert["id"], CO))
    assert cert_now["status"] == "DRAFT"


def test_com_lot_binding_required(api):
    """PRD §3.4: "When the spec's `origin` is `CUSTOMER`, the lot is COM and
    must name its bound ordering line via `order_line_id`; when the origin is
    `PLANT`, naming a line is forbidden — violations of either binding rule
    are rejected with `ERR_LOT_BINDING_INVALID`."

    Design: Corner/validations/com_lot_binding_required
    """
    spec_com = create_spec(fabric_code="FAB-COM-B", origin="CUSTOMER", grade="COM",
                           nominal_width_inches=54.0, com_credit_per_yard_cents=250)
    spec_plant = create_spec(fabric_code="FAB-A", origin="PLANT", grade="A",
                             nominal_width_inches=54.0, price_per_yard_cents=3000)
    model = create_model(
        model_code="M-NP",
        option_rules=[{
            "fabric_grade": "COM", "finish_code": "ANY", "allowed": True,
            "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    dealer = create_dealer()
    order = create_order("ORD-BND", dealer["id"])
    line = add_line(order["id"], model["id"], spec_com["id"], fabric_source="COM")

    # COM lot without order_line_id
    res1 = api.create_material_lot({
        "fabric_spec_id": spec_com["id"], "expected_yards": 10.0,
    }, RECEIVER)
    validate_error(res1, "ERR_LOT_BINDING_INVALID", expected_status=422)

    # PLANT lot with order_line_id
    res2 = api.create_material_lot({
        "fabric_spec_id": spec_plant["id"], "order_line_id": line["id"],
        "expected_yards": 10.0,
    }, RECEIVER)
    validate_error(res2, "ERR_LOT_BINDING_INVALID", expected_status=422)


def test_duplicate_order_number_rejected(api):
    """PRD §2.8: "natural keys (`model_code`, `fabric_code`, `dealer_code`,
    `cell_code`, `order_number`) must not be duplicated, else
    `ERR_DUPLICATE_NATURAL_KEY` (HTTP 409)."

    Design: Corner/validations/duplicate_order_number_rejected
    """
    dealer = create_dealer()
    create_order("ORD-DUP", dealer["id"])
    res = api.create_customer_order({
        "order_number": "ORD-DUP", "dealer_id": dealer["id"],
        "ship_to_state": "VA", "delivery_method": "WHITE_GLOVE",
    }, SALES)
    validate_error(res, "ERR_DUPLICATE_NATURAL_KEY", expected_status=409)


def test_credit_limit_exceeded_on_confirm(api):
    """PRD §3.3: "The fiscal gate comes last among these checks: the order's
    computed `total_cents` must not exceed the dealer's `credit_limit_cents`,
    or the confirm is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_limit_exceeded_on_confirm
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
    dealer = create_dealer(dealer_code="DLR-TIGHT", name="Small Town Interiors",
                           credit_limit_cents=20000)
    order = create_order("ORD-CR", dealer["id"])
    add_line(order["id"], model["id"], spec["id"], finish_code="WALNUT", quantity=2)

    res = api.confirm_order(order["id"], SALES)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=402)
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "DRAFT"


def test_cell_down_and_type_mismatch_rejected(api):
    """PRD §3.6: "A `DOWN` cell rejects new bookings with `ERR_CELL_DOWN`..."
    PRD §3.6: "The cell's type must match the operation — CUT on a CUTTING
    cell, SEW on a SEWING cell, UPHOLSTER on an UPHOLSTERY cell — else
    `ERR_CELL_TYPE_MISMATCH`."

    Design: Corner/validations/cell_down_and_type_mismatch_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-CD", quantity=1, lot_yards=30.0,
    )
    c_down = create_cell("C-DOWN", "CUTTING", 1, [])
    c_sew = create_cell("C-SEW", "SEWING", 1, [])
    get_success_data(api_client.set_cell_status(c_down["id"], {"status": "DOWN"}, PLANNER))

    # DOWN cell
    res1 = api.create_cell_booking({
        "cell_id": c_down["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-01T08:00:00Z", "end_at": "2026-06-01T09:00:00Z",
    }, PLANNER)
    validate_error(res1, "ERR_CELL_DOWN", expected_status=422)

    # CUT on SEWING cell
    res2 = api.create_cell_booking({
        "cell_id": c_sew["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-01T08:00:00Z", "end_at": "2026-06-01T09:00:00Z",
    }, PLANNER)
    validate_error(res2, "ERR_CELL_TYPE_MISMATCH", expected_status=422)


def test_component_availability_gates_cut_booking(api):
    """PRD §3.6: "A CUT booking additionally requires that every code in the
    model's `required_component_codes` have a RECEIVED supply requisition for
    the line, else `ERR_COMPONENT_NOT_RECEIVED`."
    PRD §3.6: "receiving it (only from `PLACED`, else
    `ERR_REQUISITION_INVALID_STATE`) is gated on the logical clock having
    reached the `available_date` — an early receive is rejected with
    `ERR_COMPONENT_NOT_YET_AVAILABLE`."

    Design: Corner/validations/component_availability_gates_cut_booking
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-FR", required_component_codes=["FRAME"])
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-FR", quantity=1, lot_yards=30.0,
    )
    cell = create_cell("C-CUT", "CUTTING", 1, [])

    # CUT booking without a RECEIVED requisition
    res1 = api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-01T08:00:00Z", "end_at": "2026-06-01T09:00:00Z",
    }, PLANNER)
    validate_error(res1, "ERR_COMPONENT_NOT_RECEIVED", expected_status=422)

    # Create + place a DOMESTIC requisition; clock still 2026-05-10, available 2026-05-17
    req = get_success_data(api_client.create_supply_requisition({
        "order_line_id": line["id"], "component_code": "FRAME",
        "quantity": 1, "source_type": "DOMESTIC",
    }, PLANNER))
    get_success_data(api_client.place_requisition(req["id"], PLANNER))
    res2 = api.receive_requisition(req["id"], PLANNER)
    validate_error(res2, "ERR_COMPONENT_NOT_YET_AVAILABLE", expected_status=422)

    # Advance clock to the available date — receive now succeeds
    set_clock("2026-05-17T00:00:00Z")
    ok = validate_success(api.receive_requisition(req["id"], PLANNER), 200)
    assert ok["status"] == "RECEIVED"
    assert ok["received_at"] is not None

    # CUT booking now succeeds
    booking = validate_success(api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-01T08:00:00Z", "end_at": "2026-06-01T09:00:00Z",
    }, PLANNER), 201)
    assert booking["status"] == "BOOKED"


def test_sample_allowance_boundary(api):
    """PRD §3.8: "Finally the allowance gate: the dealer's outstanding balance
    plus the new sample's value must not exceed `sample_allowance_cents`, with
    landing exactly on the allowance permitted, else
    `ERR_SAMPLE_ALLOWANCE_EXCEEDED`."

    Design: Corner/validations/sample_allowance_boundary
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    dealer = create_dealer(sample_allowance_cents=50000)
    # First loan: 30000
    get_success_data(api_client.create_showroom_sample(create_showroom_sample_payload(
        dealer_id=dealer["id"], model_id=model["id"],
        unit_serial="U-A", sample_value_cents=30000, due_back_days=30,
    ), SALES))
    # Second loan: 20000 — total 50000, exactly at the allowance, permitted
    s2 = validate_success(api.create_showroom_sample(create_showroom_sample_payload(
        dealer_id=dealer["id"], model_id=model["id"],
        unit_serial="U-B", sample_value_cents=20000, due_back_days=30,
    ), SALES), 201)
    assert s2["disposition"] == "ON_LOAN"
    # Third: 1 more cent — exceeds the allowance
    res = api.create_showroom_sample(create_showroom_sample_payload(
        dealer_id=dealer["id"], model_id=model["id"],
        unit_serial="U-C", sample_value_cents=1, due_back_days=30,
    ), SALES)
    validate_error(res, "ERR_SAMPLE_ALLOWANCE_EXCEEDED", expected_status=422)

    dealer_now = validate_success(api.get_dealer_account(dealer["id"], SALES))
    assert dealer_now["outstanding_sample_value_cents"] == 50000


def test_unit_serial_exclusivity(api):
    """PRD §3.8: "One active loan per serial: a serial with another `ON_LOAN`
    sample is rejected with `ERR_UNIT_SERIAL_UNAVAILABLE`."

    Design: Corner/validations/unit_serial_exclusivity
    """
    model = create_model(model_code="M-NP")
    dealer = create_dealer(sample_allowance_cents=100000)
    get_success_data(api_client.create_showroom_sample(create_showroom_sample_payload(
        dealer_id=dealer["id"], model_id=model["id"],
        unit_serial="U-X", sample_value_cents=10000, due_back_days=30,
    ), SALES))
    res = api.create_showroom_sample(create_showroom_sample_payload(
        dealer_id=dealer["id"], model_id=model["id"],
        unit_serial="U-X", sample_value_cents=5000, due_back_days=30,
    ), SALES)
    validate_error(res, "ERR_UNIT_SERIAL_UNAVAILABLE", expected_status=409)


def test_duplicate_active_certificate_and_shipment_rejected(api):
    """PRD §3.7: "An order may have only one active certificate — DRAFT or
    CERTIFIED — at a time; a second attempt is rejected with
    `ERR_CERTIFICATE_EXISTS`."
    PRD §3.9: "an order gets exactly one shipment — a second attempt is
    rejected with `ERR_SHIPMENT_EXISTS`."

    Design: Corner/validations/duplicate_active_certificate_and_shipment_rejected
    """
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-DUP2")
    confirm_order(order["id"])  # MATERIAL_HOLD (no stock)

    create_certificate(order["id"], standard="TB117_2013", label_lot_number="LBL-6",
                       label_count=1)
    get_success_data(api_client.create_shipment(create_shipment_payload(
        order_id=order["id"]), SHIP))

    res1 = api.create_compliance_certificate({
        "order_id": order["id"], "standard": "TB117_2013",
        "label_lot_number": "LBL-7", "label_count": 1,
    }, CO)
    validate_error(res1, "ERR_CERTIFICATE_EXISTS", expected_status=409)

    res2 = api.create_shipment(create_shipment_payload(
        order_id=order["id"], carrier_name="Old Dominion", weight_lb=90.0), SHIP)
    validate_error(res2, "ERR_SHIPMENT_EXISTS", expected_status=409)


def test_booking_blocked_while_order_on_hold(api):
    """PRD §3.6: "And the order must be in `CONFIRMED` or `IN_PRODUCTION` both
    when a booking is created and when it is started, else
    `ERR_ORDER_NOT_BOOKABLE`."
    PRD §2.8: "Existence and uniqueness — ids referenced in the path and body
    are resolved left to right, and the first missing reference produces that
    resource's 404..."

    Design: Corner/validations/booking_blocked_while_order_on_hold
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-COM",
                         option_rules=[{
                             "fabric_grade": "COM", "finish_code": "ANY",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-COM-C", origin="CUSTOMER", grade="COM",
                       nominal_width_inches=54.0, com_credit_per_yard_cents=250)
    dealer = create_dealer()
    order, line = setup_confirmed_com_order(model, spec, dealer,
                                            order_number="ORD-HOLD", quantity=1)
    cell = create_cell("C-CUT", "CUTTING", 1, ["COM_HANDLING"])

    # Booking against MATERIAL_HOLD order
    res1 = api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-01T08:00:00Z", "end_at": "2026-06-01T09:00:00Z",
    }, PLANNER)
    validate_error(res1, "ERR_ORDER_NOT_BOOKABLE", expected_status=409)

    # Existence beats state gate for shipment create on unknown order
    res2 = api.create_shipment(create_shipment_payload(
        order_id=NON_EXISTENT_UUID), SHIP)
    validate_error(res2, "ERR_ORDER_NOT_FOUND", expected_status=404)


def test_confirm_with_no_lines_rejected(api):
    """PRD §3.3: "A `SalesRep` confirms an order in `DRAFT`; the attempt is
    rejected with `ERR_ORDER_NOT_DRAFT` if the order is anywhere else, with
    `ERR_ORDER_HAS_NO_LINES` if it has no lines..."

    Design: Corner/validations/confirm_with_no_lines_rejected
    """
    dealer = create_dealer()
    order = create_order("ORD-EMPTY", dealer["id"])
    res = api.confirm_order(order["id"], SALES)
    validate_error(res, "ERR_ORDER_HAS_NO_LINES", expected_status=422)
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "DRAFT"


def test_insufficient_yardage_on_manual_allocation_rejected(api):
    """PRD §3.4: "the requested `yards` must not exceed the lot's
    `available_yards` (`ERR_INSUFFICIENT_YARDAGE` otherwise)."

    Design: Corner/validations/insufficient_yardage_on_manual_allocation_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", category="SOFA")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    # qty 6, no-match: requirement = 3.0 × 54/52 × 6 × 1.10 = 20.562
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-IY",
                                        quantity=6)
    confirm_order(order["id"])
    lot = create_available_lot(spec["id"], yards=20.0, measured_width_inches=54.0)

    # 25.0 > 20.0 available
    res1 = api.create_material_allocation({
        "lot_id": lot["id"], "order_line_id": line["id"], "yards": 25.0,
    }, PLANNER)
    validate_error(res1, "ERR_INSUFFICIENT_YARDAGE", expected_status=422)

    # Exactly 20.0 succeeds — boundary inclusive
    alloc = validate_success(api.create_material_allocation({
        "lot_id": lot["id"], "order_line_id": line["id"], "yards": 20.0,
    }, PLANNER), 201)
    assert alloc["status"] == "ACTIVE"

    lot_now = validate_success(api.get_material_lot(lot["id"], RECEIVER))
    assert lot_now["available_yards"] == pytest.approx(0.0, abs=0.001)

    line_now = validate_success(api.get_order_line(line["id"], SALES))
    assert line_now["allocated_yards"] == pytest.approx(20.0, abs=0.001)
    assert line_now["status"] == "MATERIAL_SHORTFALL"  # 20.0 < 20.562


def test_approve_with_insufficient_allocation_rejected(api):
    """PRD §3.5: "if the line's `allocated_yards` falls short of the computed
    final figure the approval is rejected with `ERR_INSUFFICIENT_ALLOCATION`
    (HTTP 422)."

    Design: Corner/validations/approve_with_insufficient_allocation_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-IA", quantity=2, lot_yards=30.0,
    )
    # line allocated 7.165 (provisional = 3.0 × 54/52 × 2 × 1.15 = 7.165)
    plan = create_draft_cut_plan(line)

    # marker 7.2 → final 7.200 > 7.165 allocated — rejected
    res1 = api.approve_cut_plan(plan["id"], {"marker_length_yards": 7.2}, PLANNER)
    validate_error(res1, "ERR_INSUFFICIENT_ALLOCATION", expected_status=422)

    # marker 7.1 → final 7.100 ≤ 7.165 — succeeds
    ok = validate_success(api.approve_cut_plan(
        plan["id"], {"marker_length_yards": 7.1}, PLANNER), 200)
    assert ok["status"] == "APPROVED"


def test_rejected_plant_lot_not_returnable(api):
    """PRD §3.4: "return-to-customer requires the lot in `REJECTED` (else
    `ERR_LOT_INVALID_STATE` — an `AVAILABLE` lot in particular can never be
    returned) and `ownership` `CUSTOMER` (else `ERR_LOT_NOT_RETURNABLE`)."

    Design: Corner/validations/rejected_plant_lot_not_returnable
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-COM",
                         option_rules=[{
                             "fabric_grade": "COM", "finish_code": "ANY",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec_p = create_spec(fabric_code="FAB-P", origin="PLANT", grade="A",
                         nominal_width_inches=54.0, price_per_yard_cents=3000)
    spec_c = create_spec(fabric_code="FAB-C", origin="CUSTOMER", grade="COM",
                         nominal_width_inches=54.0, com_credit_per_yard_cents=250)
    dealer = create_dealer()
    # REJECTED plant lot
    lot_p = create_lot(spec_p["id"], expected_yards=10.0)
    receive_lot(lot_p["id"], received_yards=10.0)
    inspect_lot_fail(lot_p["id"], received_yards=10.0)

    # REJECTED COM lot
    order, line = setup_confirmed_com_order(model, spec_c, dealer,
                                            order_number="ORD-RET", quantity=1)
    lot_c = create_lot(spec_c["id"], expected_yards=8.0, order_line_id=line["id"])
    receive_lot(lot_c["id"], received_yards=8.0)
    inspect_lot_fail(lot_c["id"], received_yards=8.0)

    # PLANT rejected lot cannot be returned
    res1 = api.return_lot_to_customer(lot_p["id"], RECEIVER)
    validate_error(res1, "ERR_LOT_NOT_RETURNABLE", expected_status=409)

    # COM rejected lot is returned
    ok = validate_success(api.return_lot_to_customer(lot_c["id"], RECEIVER), 200)
    assert ok["status"] == "RETURNED"

    line_after = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after["status"] == "MATERIAL_SHORTFALL"
    order_after = validate_success(api.get_customer_order(order["id"], SALES))
    assert order_after["status"] == "MATERIAL_HOLD"


def test_discontinued_model_and_suspended_dealer_rejected(api):
    """PRD §3.1: "when the planner discontinues it, the status moves to
    `DISCONTINUED` and any later attempt to add an order line against that
    model is rejected with `ERR_MODEL_NOT_ACTIVE`."
    PRD §3.2: "Orders and samples cannot be created against a `SUSPENDED`
    dealer — such attempts are rejected with `ERR_DEALER_SUSPENDED`."

    Design: Corner/validations/discontinued_model_and_suspended_dealer_rejected
    """
    model_old = create_model(model_code="M-OLD")
    get_success_data(api_client.discontinue_product_model(model_old["id"], PLANNER))
    spec = create_spec(fabric_code="FAB-A")
    dealer_ok = create_dealer(dealer_code="DLR-OK")
    dealer_susp = create_dealer(dealer_code="DLR-SUSP", name="Shady Grove")
    get_success_data(api_client.set_dealer_status(
        dealer_susp["id"], {"status": "SUSPENDED"}, SALES))
    order_ok = create_order("ORD-DIS", dealer_ok["id"])

    # Line referencing a DISCONTINUED model
    res1 = api.create_order_line({
        "order_id": order_ok["id"], "model_id": model_old["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "ESPRESSO", "quantity": 1,
    }, SALES)
    validate_error(res1, "ERR_MODEL_NOT_ACTIVE", expected_status=409)

    # Order against SUSPENDED dealer
    res2 = api.create_customer_order({
        "order_number": "ORD-SUSP", "dealer_id": dealer_susp["id"],
        "ship_to_state": "NC", "delivery_method": "LTL_FREIGHT",
    }, SALES)
    validate_error(res2, "ERR_DEALER_SUSPENDED", expected_status=409)


def test_draft_order_blocks_line_dependent_writes(api):
    """PRD §3.2: "Adding an **OrderLine** requires the order to still be in
    `DRAFT` (otherwise `ERR_ORDER_NOT_DRAFT`)..."
    PRD §3.9: "Creating a **Shipment** requires the order in `CONFIRMED`,
    `MATERIAL_HOLD`, `IN_PRODUCTION`, `QUALITY_REVIEW`, or `READY_TO_SHIP`
    (else `ERR_ORDER_NOT_READY_TO_SHIP`)..."
    PRD §3.4: "the target line must be in `MATERIAL_SHORTFALL` or `ALLOCATED`
    (`ERR_LINE_STAGE_MISMATCH` otherwise)..."

    Design: Corner/validations/draft_order_blocks_line_dependent_writes
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order_draft = create_order("ORD-DR", dealer["id"])
    line_pending = add_line(order_draft["id"], model["id"], spec["id"])
    lot = create_available_lot(spec["id"], yards=20.0)
    order_conf = create_order("ORD-DR2", dealer["id"])
    add_line(order_conf["id"], model["id"], spec["id"])
    confirm_order(order_conf["id"])

    # Add line to a confirmed order
    res1 = api.create_order_line({
        "order_id": order_conf["id"], "model_id": model["id"],
        "fabric_spec_id": spec["id"], "fabric_source": "PLANT_STOCK",
        "finish_code": "ESPRESSO", "quantity": 1,
    }, SALES)
    validate_error(res1, "ERR_ORDER_NOT_DRAFT", expected_status=409)

    # Create shipment for a DRAFT order
    res2 = api.create_shipment(create_shipment_payload(order_id=order_draft["id"]), SHIP)
    validate_error(res2, "ERR_ORDER_NOT_READY_TO_SHIP", expected_status=409)

    # Manual allocation to a PENDING line
    res3 = api.create_material_allocation({
        "lot_id": lot["id"], "order_line_id": line_pending["id"], "yards": 3.0,
    }, PLANNER)
    validate_error(res3, "ERR_LINE_STAGE_MISMATCH", expected_status=409)


def test_pass_quality_gates(api):
    """PRD §3.7: "a verdict attempted in any other status is rejected with
    `ERR_ORDER_NOT_IN_QUALITY_REVIEW`."
    PRD §3.7: "Passing quality requires a `CERTIFIED` compliance certificate
    for the order; a draft or missing certificate is not enough and draws
    `ERR_COMPLIANCE_NOT_CERTIFIED`."

    Design: Corner/validations/pass_quality_gates
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    # Confirm order; pass-quality on DRAFT order (before confirm) — captures err0
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-PQ",
                                        quantity=1)
    qi = make_quality_inspector_headers("qi-1")
    res0 = api.pass_quality(order["id"], qi)
    validate_error(res0, "ERR_ORDER_NOT_IN_QUALITY_REVIEW", expected_status=409)

    # Stock the lot BEFORE confirm so the FEFO reservation covers the line
    # (PRD §3.3: plant-stock lines reserve at confirm; PRD §3.4 scopes
    # inspect-time auto-allocation to customer-owned lots only).
    lot = create_available_lot(spec["id"], yards=30.0)
    confirm_order(order["id"])
    # Drive to QUALITY_REVIEW — the line was allocated at confirm.
    from test_helpers import drive_line_through_production, setup_three_cells
    cells = setup_three_cells()
    drive_line_through_production(line, *cells, marker_length_yards=3.5)
    order_qr = validate_success(api.get_customer_order(order["id"], SALES))
    assert order_qr["status"] == "QUALITY_REVIEW"

    # DRAFT-only certificate is not enough
    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-PQ", label_count=1)
    res1 = api.pass_quality(order["id"], qi)
    validate_error(res1, "ERR_COMPLIANCE_NOT_CERTIFIED", expected_status=409)

    # Certify with a different operator and pass
    validate_success(api.certify_certificate(
        cert["id"], make_compliance_officer_headers("co-2")), 200)
    passed = validate_success(api.pass_quality(order["id"], qi), 200)
    assert passed["status"] == "READY_TO_SHIP"
    assert passed["quality_result"] == "PASSED"
    line_done = validate_success(api.get_order_line(line["id"], SALES))
    assert line_done["status"] == "COMPLETED"


def test_white_glove_pickup_requires_condition_check(api):
    """PRD §3.9: "for a `WHITE_GLOVE` shipment the handoff is gated —
    `condition_check_passed` must be true at pickup, else
    `ERR_WHITE_GLOVE_CHECK_REQUIRED`."

    Design: Corner/validations/white_glove_pickup_requires_condition_check
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    # Build WHITE_GLOVE order ready to ship
    lot = create_available_lot(spec["id"], yards=30.0)
    order = create_order("ORD-WG", dealer["id"], delivery_method="WHITE_GLOVE")
    line = add_line(order["id"], model["id"], spec["id"], quantity=1)
    confirm_order(order["id"])
    from test_helpers import drive_line_through_production, setup_three_cells
    cells = setup_three_cells()
    drive_line_through_production(line, *cells, marker_length_yards=3.5)
    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-WG", label_count=1)
    validate_success(api.certify_certificate(
        cert["id"], make_compliance_officer_headers("co-2")), 200)
    validate_success(api.pass_quality(
        order["id"], make_quality_inspector_headers("qi-1")), 200)

    ship = get_success_data(api_client.create_shipment(create_shipment_payload(
        order_id=order["id"], carrier_name="WhiteGloveCo",
        weight_lb=240.0, length_in=60.0, width_in=30.0, height_in=36.0,
        declared_value_cents=0, piece_count=3,
    ), SHIP))
    assert ship["method"] == "WHITE_GLOVE"
    get_success_data(api_client.rate_shipment(ship["id"], SHIP))
    get_success_data(api_client.tender_shipment(ship["id"], SHIP))

    # Pickup with condition_check_passed false → rejection
    res = api.record_pickup(ship["id"], {"condition_check_passed": False}, SHIP)
    validate_error(res, "ERR_WHITE_GLOVE_CHECK_REQUIRED", expected_status=422)
    ship_now = validate_success(api.get_shipment(ship["id"], SHIP))
    assert ship_now["status"] == "TENDERED"

    # With true → succeeds, order SHIPPED
    ok = validate_success(api.record_pickup(
        ship["id"], {"condition_check_passed": True}, SHIP), 200)
    assert ok["status"] == "PICKED_UP"
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "SHIPPED"
