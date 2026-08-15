"""Composite setup helpers for the PRD §3 workflows.

Every helper builds preconditions from scratch via the public endpoints (the
harness restarts the server before each test, so nothing carries over). Setup
calls use the lenient get_success_data validator so failures surface as clear
"Setup failed" messages. Ownership-gated calls always thread the entity-backed
Customer id through make_customer_headers (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_lane_payload,
    create_fab_order_payload,
    create_stackup_payload,
    create_spec_line_payload,
    create_panel_array_payload,
    create_drill_program_payload,
    create_laminate_lot_payload,
    create_reservation_payload,
    create_coupon_payload,
    create_measurement_payload,
    create_lab_booking_payload,
    create_etest_run_payload,
    complete_etest_run_payload,
    create_defect_payload,
    create_invoice_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_cam_operator_headers,
    make_process_engineer_headers,
)

FAB_ADMIN = TEST_USERS["fab_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
CAM = TEST_USERS["cam_operator_headers"]
ENG = TEST_USERS["process_engineer_headers"]
QI = TEST_USERS["quality_inspector_headers"]
PLANNER = TEST_USERS["production_planner_headers"]

# Fixed opaque operator ids used wherever the drill-program segregation-of-duties
# anchor matters (PRD §3.4): the author is cam_1, the approver is eng_1.
CAM_AUTHOR_ID = "cam_1"
ENG_APPROVER_ID = "eng_1"


# ---------------------------------------------------------------------------
# Tier 0: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5). Returns {current_utc}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, FAB_ADMIN))


def create_customer(company_name="Test Circuits", contact_email=None,
                    credit_limit_cents=1_000_000, tax_exempt=False) -> dict:
    email = contact_email or f"ops@{company_name.lower().replace(' ', '-')}.example"
    payload = create_customer_payload(
        company_name=company_name, contact_email=email,
        credit_limit_cents=credit_limit_cents, tax_exempt=tax_exempt,
    )
    return get_success_data(api_client.create_customer(payload, FAB_ADMIN))


def create_lane(lane_code="QT3", turn_days=3, capacity_boards_per_day=500,
                premium_multiplier=1.50, active=True) -> dict:
    payload = create_lane_payload(
        lane_code=lane_code, turn_days=turn_days,
        capacity_boards_per_day=capacity_boards_per_day,
        premium_multiplier=premium_multiplier, active=active,
    )
    return get_success_data(api_client.create_lane(payload, FAB_ADMIN))


def create_order(customer_id, *, service_lane="STANDARD", quick_turn_lane_id=None,
                 board_x_mils=C.G1_BOARD_X_MILS, board_y_mils=C.G1_BOARD_Y_MILS,
                 layer_count=2, surface_finish="HASL",
                 quantity_boards=C.G1_QUANTITY_BOARDS,
                 requested_ship_date=C.DEFAULT_SHIP_DATE) -> dict:
    """Create an order as its owning Customer (PRD §3.1). Returns QUOTED order."""
    payload = create_fab_order_payload(
        customer_id,
        service_lane=service_lane,
        board_x_mils=board_x_mils, board_y_mils=board_y_mils,
        layer_count=layer_count, surface_finish=surface_finish,
        quantity_boards=quantity_boards, requested_ship_date=requested_ship_date,
    )
    if quick_turn_lane_id is not None:
        payload["quick_turn_lane_id"] = quick_turn_lane_id
    return get_success_data(
        api_client.create_fab_order(payload, make_customer_headers(customer_id))
    )


def get_fab_order(order_id) -> dict:
    return get_success_data(api_client.get_fab_order(order_id, PLANNER))


def create_stackup(order_id, *, revision=1, total_thickness_mils=62,
                   dielectric_material="FR4_TG170", copper_weight_oz=1,
                   impedance_controlled=False) -> dict:
    payload = create_stackup_payload(
        revision=revision, total_thickness_mils=total_thickness_mils,
        dielectric_material=dielectric_material, copper_weight_oz=copper_weight_oz,
        impedance_controlled=impedance_controlled,
    )
    return get_success_data(api_client.create_stackup(order_id, payload, CAM))


def add_spec_line(stackup_id, *, layer_name="L1", target_ohms=50.0,
                  tolerance_plus_ohms=5.0, tolerance_minus_ohms=5.0,
                  line_type="SINGLE_ENDED", coupon_required=True) -> dict:
    payload = create_spec_line_payload(
        layer_name=layer_name, target_ohms=target_ohms,
        tolerance_plus_ohms=tolerance_plus_ohms,
        tolerance_minus_ohms=tolerance_minus_ohms,
        line_type=line_type, coupon_required=coupon_required,
    )
    return get_success_data(api_client.create_spec_line(stackup_id, payload, CAM))


def create_and_lock_stackup(order_id, *, spec_lines=(), **stackup_kw):
    """Create a stackup, attach any impedance spec lines, then lock it (PRD §3.2).

    spec_lines: iterable of per-line override dicts for add_spec_line.
    Returns (locked_stackup, [spec_line, ...]).
    """
    if spec_lines:
        stackup_kw.setdefault("impedance_controlled", True)
    stackup = create_stackup(order_id, **stackup_kw)
    lines = [add_spec_line(stackup["id"], **spec) for spec in spec_lines]
    locked = get_success_data(api_client.lock_stackup(stackup["id"], ENG))
    return locked, lines


def submit_dfm(order_id, customer_id) -> dict:
    return get_success_data(
        api_client.submit_dfm(order_id, make_customer_headers(customer_id))
    )


def dfm_approve(order_id) -> dict:
    return get_success_data(api_client.dfm_approve(order_id, ENG))


def create_panel_array(order_id, *, array_x=C.G1_ARRAY_X, array_y=C.G1_ARRAY_Y,
                       panel_width_mils=C.G1_PANEL_WIDTH_MILS,
                       panel_height_mils=C.G1_PANEL_HEIGHT_MILS,
                       extra_payload=None) -> dict:
    """Create a panel array, threading the OCC field expected_fab_order_version
    from a fresh read of the order (PRD §2.6)."""
    version = get_fab_order(order_id)["version"]
    payload = create_panel_array_payload(
        version,
        array_x=array_x, array_y=array_y,
        panel_width_mils=panel_width_mils, panel_height_mils=panel_height_mils,
    )
    if extra_payload:
        payload.update(extra_payload)
    return get_success_data(api_client.create_panel_array(order_id, payload, CAM))


def create_and_release_array(order_id, **array_kw) -> dict:
    array = create_panel_array(order_id, **array_kw)
    return get_success_data(api_client.release_panel_array(array["id"], CAM))


def create_drill_program(order_id, *, min_hole_mils=8, hole_count=1200,
                         author_id=CAM_AUTHOR_ID) -> dict:
    payload = create_drill_program_payload(
        min_hole_mils=min_hole_mils, hole_count=hole_count,
    )
    return get_success_data(
        api_client.create_drill_program(order_id, payload,
                                        make_cam_operator_headers(author_id))
    )


def submit_drill_program(program_id, author_id=CAM_AUTHOR_ID) -> dict:
    return get_success_data(
        api_client.submit_drill_program(program_id, make_cam_operator_headers(author_id))
    )


def approve_drill_program(program_id, approver_id=ENG_APPROVER_ID) -> dict:
    return get_success_data(
        api_client.approve_drill_program(program_id,
                                         make_process_engineer_headers(approver_id))
    )


def create_approved_drill_program(order_id, *, min_hole_mils=8, hole_count=1200) -> dict:
    program = create_drill_program(order_id, min_hole_mils=min_hole_mils,
                                   hole_count=hole_count)
    submit_drill_program(program["id"])
    return approve_drill_program(program["id"])


def create_laminate_lot(lot_code="LOT-1", *, material_code="FR4_TG170",
                        manufacture_date=C.DEFAULT_MANUFACTURE_DATE,
                        panels_total=100) -> dict:
    payload = create_laminate_lot_payload(
        material_code=material_code, lot_code=lot_code,
        manufacture_date=manufacture_date, panels_total=panels_total,
    )
    return get_success_data(api_client.create_laminate_lot(payload, ENG))


def qualify_lot(lot_id) -> dict:
    return get_success_data(api_client.qualify_lot(lot_id, QI))


def create_qualified_lot(lot_code="LOT-1", **lot_kw) -> dict:
    lot = create_laminate_lot(lot_code, **lot_kw)
    return qualify_lot(lot["id"])


def get_laminate_lot(lot_id) -> dict:
    return get_success_data(api_client.get_laminate_lot(lot_id, PLANNER))


def reserve_panels(order_id, array_id, lot_id, panels_allocated) -> dict:
    """Reserve panels, threading the OCC field expected_laminate_lot_version
    from a fresh read of the lot (PRD §2.6)."""
    lot = get_laminate_lot(lot_id)
    payload = create_reservation_payload(
        order_id, array_id, lot_id, lot["version"],
        panels_allocated=panels_allocated,
    )
    return get_success_data(api_client.create_reservation(payload, PLANNER))


def release_order(order_id) -> dict:
    return get_success_data(api_client.release_order(order_id, PLANNER))


def start_production(order_id) -> dict:
    return get_success_data(api_client.start_production(order_id, PLANNER))


def create_coupon(order_id, spec_line_id, panel_ref="P01") -> dict:
    payload = create_coupon_payload(spec_line_id, panel_ref=panel_ref)
    return get_success_data(api_client.create_coupon(order_id, payload, QI))


def create_booking(coupon_id, starts_at, ends_at, station="MICROSECTION_A") -> dict:
    payload = create_lab_booking_payload(
        coupon_id, station=station, starts_at=starts_at, ends_at=ends_at,
    )
    return get_success_data(api_client.create_lab_booking(payload, QI))


def record_measurement(coupon_id, booking_id, measured_ohms, measured_ohms_b=None) -> dict:
    payload = create_measurement_payload(booking_id, measured_ohms=measured_ohms)
    if measured_ohms_b is not None:
        payload["measured_ohms_b"] = measured_ohms_b
    return get_success_data(api_client.create_measurement(coupon_id, payload, QI))


def book_and_measure(coupon_id, measured_ohms, starts_at, ends_at,
                     measured_ohms_b=None):
    """Book a lab window and record a measurement against it. Returns
    (booking, measurement). The window must cover the current logical clock."""
    booking = create_booking(coupon_id, starts_at, ends_at)
    measurement = record_measurement(coupon_id, booking["id"], measured_ohms,
                                     measured_ohms_b)
    return booking, measurement


def create_and_pass_etest(order_id, boards_tested=C.G1_QUANTITY_BOARDS) -> dict:
    run = get_success_data(
        api_client.create_etest_run(order_id, create_etest_run_payload(), QI)
    )
    get_success_data(api_client.start_etest_run(run["id"], QI))
    return get_success_data(
        api_client.complete_etest_run(
            run["id"], complete_etest_run_payload(boards_tested=boards_tested), QI,
        )
    )


# ---------------------------------------------------------------------------
# Tier 1-2: order pipeline progression
# ---------------------------------------------------------------------------

def prepare_order(*, company_name="Test Circuits", contact_email=None,
                  credit_limit_cents=1_000_000,
                  service_lane="STANDARD", lane=None,
                  quantity_boards=C.G1_QUANTITY_BOARDS,
                  requested_ship_date=C.DEFAULT_SHIP_DATE,
                  board_x_mils=C.G1_BOARD_X_MILS, board_y_mils=C.G1_BOARD_Y_MILS,
                  layer_count=2, surface_finish="HASL",
                  spec_lines=(), stackup_kw=None,
                  array_kw=None, with_array=True,
                  min_hole_mils=8, hole_count=1200, with_drill=True,
                  lot_code="LOT-1", manufacture_date=C.DEFAULT_MANUFACTURE_DATE,
                  panels_total=100, panels_to_reserve=C.G1_PANELS_REQUIRED,
                  with_lot=True, with_reservation=True,
                  advance_to="AWAITING_LAMINATE") -> dict:
    """Build a customer + order and walk it down the intake pipeline.

    advance_to: "QUOTED" (no stackup actions beyond creation), "DFM_REVIEW"
    (submit only) or "AWAITING_LAMINATE" (submit + approve). Returns a context
    dict with keys: customer, order, stackup, spec_lines, array, drill, lot,
    reservation (entries are None for steps that were skipped).
    """
    ctx = {"customer": None, "order": None, "stackup": None, "spec_lines": [],
           "array": None, "drill": None, "lot": None, "reservation": None}

    ctx["customer"] = create_customer(company_name, contact_email, credit_limit_cents)
    cust_id = ctx["customer"]["id"]
    ctx["order"] = create_order(
        cust_id,
        service_lane=service_lane,
        quick_turn_lane_id=lane["id"] if lane else None,
        board_x_mils=board_x_mils, board_y_mils=board_y_mils,
        layer_count=layer_count, surface_finish=surface_finish,
        quantity_boards=quantity_boards, requested_ship_date=requested_ship_date,
    )
    order_id = ctx["order"]["id"]

    ctx["stackup"], ctx["spec_lines"] = create_and_lock_stackup(
        order_id, spec_lines=spec_lines, **(stackup_kw or {}),
    )

    if advance_to in ("DFM_REVIEW", "AWAITING_LAMINATE"):
        ctx["order"] = submit_dfm(order_id, cust_id)
    if advance_to == "AWAITING_LAMINATE":
        ctx["order"] = dfm_approve(order_id)

    if with_array:
        ctx["array"] = create_and_release_array(order_id, **(array_kw or {}))
    if with_drill:
        ctx["drill"] = create_approved_drill_program(
            order_id, min_hole_mils=min_hole_mils, hole_count=hole_count,
        )
    if with_lot:
        ctx["lot"] = create_qualified_lot(
            lot_code=lot_code, manufacture_date=manufacture_date,
            panels_total=panels_total,
        )
    if with_reservation:
        ctx["reservation"] = reserve_panels(
            order_id, ctx["array"]["id"], ctx["lot"]["id"], panels_to_reserve,
        )
    ctx["order"] = get_fab_order(order_id)
    return ctx


def setup_released_order(**kw) -> dict:
    """Order prepared through AWAITING_LAMINATE and released (PRD §3.6)."""
    ctx = prepare_order(**kw)
    ctx["order"] = release_order(ctx["order"]["id"])
    return ctx


def setup_in_production(**kw) -> dict:
    """Released order with reservations CONSUMED by production start (PRD §3.6)."""
    ctx = setup_released_order(**kw)
    ctx["order"] = start_production(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3-5: quality loop and full lifecycle
# ---------------------------------------------------------------------------

def pass_coupon(coupon_id, reading=52.0, reading_b=None) -> dict:
    """Measure a coupon PASS inside the default-clock window (PRD §3.7)."""
    _, measurement = book_and_measure(
        coupon_id, reading, *C.WINDOW_AT_DEFAULT_CLOCK, measured_ohms_b=reading_b,
    )
    return measurement


def drive_coupon_to_final_fail(coupon_id, fail_readings=(60.0, 61.0, 62.0)) -> None:
    """Drive a coupon through FAIL -> retest -> FAIL -> retest -> FAIL(final).

    The third failure lands with retest_count == MAX_RETESTS (PRD §3.7), which
    flips the order's quality_disposition to FAILED, auto-creates the IMPEDANCE
    defect record, and scraps the array's boards_per_panel.
    """
    book_and_measure(coupon_id, fail_readings[0], *C.WINDOW_AT_DEFAULT_CLOCK)
    get_success_data(api_client.retest_coupon(coupon_id, QI))
    set_clock(C.CLOCK_0100)
    book_and_measure(coupon_id, fail_readings[1], *C.WINDOW_AT_0100)
    get_success_data(api_client.retest_coupon(coupon_id, QI))
    set_clock(C.CLOCK_0200)
    book_and_measure(coupon_id, fail_readings[2], *C.WINDOW_AT_0200)


def setup_awaiting_etest(*, pass_reading=52.0, **kw) -> dict:
    """In-production order whose required coupon has PASSED, then complete-fab
    (PRD §3.7): order lands in AWAITING_ETEST with disposition PASSED.
    With spec_lines=() the stackup carries no coupon_required lines, so the
    coupon gate is vacuous and no coupon is created."""
    if "spec_lines" not in kw:
        kw["spec_lines"] = ({"layer_name": "L1", "target_ohms": 50.0,
                             "tolerance_plus_ohms": 5.0, "tolerance_minus_ohms": 5.0,
                             "line_type": "SINGLE_ENDED", "coupon_required": True},)
    ctx = setup_in_production(**kw)
    ctx["coupon"] = None
    if ctx["spec_lines"]:
        coupon = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])
        pass_coupon(coupon["id"], reading=pass_reading)
        ctx["coupon"] = coupon
    ctx["order"] = get_success_data(api_client.complete_fab(ctx["order"]["id"], PLANNER))
    return ctx


def setup_completed_order(**kw) -> dict:
    """AWAITING_ETEST order plus a PASS e-test run: order lands COMPLETED (PRD §3.8)."""
    ctx = setup_awaiting_etest(**kw)
    create_and_pass_etest(ctx["order"]["id"],
                          boards_tested=ctx["order"]["quantity_boards"])
    ctx["order"] = get_fab_order(ctx["order"]["id"])
    return ctx


def setup_shipped_order(**kw) -> dict:
    """Full lifecycle through SHIPPED: COMPLETED order + issued invoice + ship
    (PRD §3.9). The context gains an 'invoice' entry."""
    ctx = setup_completed_order(**kw)
    invoice = get_success_data(
        api_client.create_final_invoice(
            ctx["order"]["id"], create_invoice_payload(), PLANNER,
        )
    )
    get_success_data(api_client.issue_invoice(invoice["id"], SALES))
    ctx["order"] = get_success_data(api_client.ship_order(ctx["order"]["id"], PLANNER))
    ctx["invoice"] = invoice
    return ctx
