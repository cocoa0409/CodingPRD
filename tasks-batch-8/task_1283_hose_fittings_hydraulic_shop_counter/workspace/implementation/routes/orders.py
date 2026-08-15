"""Assembly orders: draft/quote (PRD §3.3), confirm with the fixed check
sequence, build bench (§3.4), settlement and cancellation (§3.5)."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, new_entity, new_line_entity, touch, pub
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ORDER_TERMINAL,
    ERR_PRESSURE_RATING_MISMATCH, ERR_WAIVER_REQUIRED,
    ERR_CRIMP_OUT_OF_TOLERANCE, ERR_TEST_PRESSURE_TOO_LOW,
    ERR_TAG_SERIAL_TAKEN, ERR_REEL_NOT_USABLE, ERR_ASSET_NOT_ACTIVE,
    ERR_CREDIT_HOLD, ERR_INSUFFICIENT_REEL_LENGTH,
    ERR_INSUFFICIENT_COUPLING_STOCK,
)
from middleware import (
    require_roles, body, get_or_404, check_customer_scope,
    get_str, get_int, get_num, get_bool, present,
)
from response import success, list_response
from services import (
    assembly_total, material_hose_cents, waste_surcharge_cents,
    refresh_reel_status, coupling_reserved_qty, order_lines,
    serialize_order, complete_order, MIN_REMNANT_MM, TEST_PRESSURE_MULTIPLIER,
)

bp = Blueprint("orders", __name__)

COUNTER_ROLES = ("CounterSales", "ShopManager")
ORDER_READ_ROLES = ("ShopManager", "CounterSales", "ShopTechnician", "Customer")


def _get_order(oid):
    return get_or_404(store.orders, oid, "order")


def _check_terminal(order):
    """Priority 4: terminal lockdown on COMPLETED / CANCELLED orders."""
    if order["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(ERR_ORDER_TERMINAL, 409,
                       "AssemblyOrder already {}".format(order["status"]))


@bp.post("/api/assembly-orders")
def create_order():
    require_roles(*COUNTER_ROLES)
    data = body()
    # existence (priority 3), body FKs left to right:
    # customer_id -> reel_id -> equipment_asset_id -> line coupling_ids
    # (a missing required FK is a malformed request; a present but unknown
    # one is the resource's 404)
    customer = get_or_404(store.customers, get_str(data, "customer_id"), "customer")
    reel = get_or_404(store.reels, get_str(data, "reel_id"), "reel")
    asset = None
    if present(data, "equipment_asset_id"):
        asset = get_or_404(store.assets, data["equipment_asset_id"], "asset")
    raw_lines = data.get("lines")
    line_couplings = []
    if raw_lines is not None:
        if not isinstance(raw_lines, list):
            raise ApiError(ERR_INVALID_REQUEST, 400, "lines must be an array")
        for lr in raw_lines:
            if not isinstance(lr, dict):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "each line must be an object")
            line_couplings.append(
                get_or_404(store.couplings, get_str(lr, "coupling_id"), "coupling"))
    # referential (priority 16): a drafted order may not target a
    # decommissioned asset
    if asset is not None and asset["status"] != "ACTIVE":
        raise ApiError(ERR_ASSET_NOT_ACTIVE, 422,
                       "Equipment asset is DECOMMISSIONED")
    # malformed request (priority 20): field shapes last
    cut_length_mm = get_int(data, "cut_length_mm", min_val=1)
    required_psi = get_int(data, "required_working_pressure_psi")
    spec = get_num(data, "crimp_diameter_spec_mm")
    tolerance = get_num(data, "crimp_tolerance_mm", required=False, default=0.2)
    crimp_count = get_int(data, "crimp_count", required=False, default=2)
    estimated = get_int(data, "estimated_labor_minutes")
    is_emergency = get_bool(data, "is_emergency", required=False, default=False)
    app_error = get_bool(data, "application_error_suspected",
                         required=False, default=False)
    quantities = []
    if raw_lines is not None:
        for lr in raw_lines:
            quantities.append(get_int(lr, "quantity", min_val=1))

    order = new_entity()
    order.update({
        "customer_id": customer["id"],
        "reel_id": reel["id"],
        "equipment_asset_id": asset["id"] if asset else None,
        "cut_length_mm": cut_length_mm,
        "required_working_pressure_psi": required_psi,
        "crimp_diameter_spec_mm": spec,
        "crimp_tolerance_mm": tolerance,
        "crimp_count": crimp_count,
        "estimated_labor_minutes": estimated,
        "is_emergency": is_emergency,
        "application_error_suspected": app_error,
        "waiver_signed": False,
        "waiver_signed_by": None,
        "waiver_liability_cents": None,
        "measured_crimp_diameter_mm": None,
        "actual_labor_minutes": None,
        "test_pressure_psi": None,
        "test_result": None,
        "tag_serial": None,
        "scrap_charged_mm": 0,
        "status": "DRAFT",
        "waste_surcharge_cents": 0,
        "final_total_cents": None,
    })
    store.orders[order["id"]] = order
    # lines snapshot the coupling unit price at creation; totals are exact
    for coupling, qty in zip(line_couplings, quantities):
        line = new_line_entity()
        line.update({
            "assembly_order_id": order["id"],
            "coupling_id": coupling["id"],
            "quantity": qty,
            "unit_price_cents": coupling["unit_price_cents"],
            "line_total_cents": qty * coupling["unit_price_cents"],
        })
        store.lines[line["id"]] = line
    # hose material charge computed once at creation (PRD §3.3)
    order["material_hose_cents"] = material_hose_cents(cut_length_mm, reel)
    # provisional variant, fixed at create (waste is zero at draft)
    order["quoted_total_cents"] = assembly_total(order, estimated)
    return success(serialize_order(order), status=201)


@bp.get("/api/assembly-orders")
def list_orders():
    uid, role = require_roles(*ORDER_READ_ROLES)
    customer_id = request.args.get("customer_id")
    reel_id = request.args.get("reel_id")
    asset_id = request.args.get("equipment_asset_id")
    status = request.args.get("status")
    items = list(store.orders.values())
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == uid]
        if customer_id is not None and customer_id != uid:
            items = []
    elif customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if reel_id is not None:
        items = [o for o in items if o["reel_id"] == reel_id]
    if asset_id is not None:
        items = [o for o in items if o["equipment_asset_id"] == asset_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response([serialize_order(o) for o in items])


@bp.get("/api/assembly-orders/<oid>")
def get_order(oid):
    uid, role = require_roles(*ORDER_READ_ROLES)
    order = _get_order(oid)
    check_customer_scope(role, uid, order["customer_id"])
    return success(serialize_order(order), status=200)


@bp.get("/api/assembly-orders/<oid>/lines")
def list_order_lines(oid):
    uid, role = require_roles(*ORDER_READ_ROLES)
    order = _get_order(oid)
    check_customer_scope(role, uid, order["customer_id"])
    return list_response(order_lines(order["id"]))


@bp.post("/api/assembly-orders/<oid>/confirm")
def confirm_order(oid):
    require_roles(*COUNTER_ROLES)
    order = _get_order(oid)
    _check_terminal(order)
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Order is not DRAFT")
    data = body()
    reel = store.reels[order["reel_id"]]
    customer = store.customers[order["customer_id"]]
    # Fixed confirm sequence (PRD §3.3): pressure -> waiver -> reel usable ->
    # credit hold -> length -> coupling stock -> field shapes
    if order["required_working_pressure_psi"] > reel["working_pressure_psi"]:
        raise ApiError(ERR_PRESSURE_RATING_MISMATCH, 422,
                       "required_working_pressure_psi exceeds the reel rating")
    waiver_by = data.get("waiver_signed_by")
    waiver_cents = data.get("waiver_liability_cents")
    if order["application_error_suspected"] and (waiver_by is None
                                                 or waiver_cents is None):
        raise ApiError(ERR_WAIVER_REQUIRED, 422,
                       "application_error_suspected order requires "
                       "waiver_signed_by and waiver_liability_cents")
    if reel["status"] not in ("AVAILABLE", "LOW"):
        raise ApiError(ERR_REEL_NOT_USABLE, 422,
                       "Reel is {} ".format(reel["status"]))
    if customer["credit_hold"]:
        raise ApiError(ERR_CREDIT_HOLD, 402, "Customer is on credit hold")
    if order["cut_length_mm"] > reel["remaining_length_mm"]:
        raise ApiError(ERR_INSUFFICIENT_REEL_LENGTH, 422,
                       "cut_length_mm exceeds reel remaining length")
    for line in order_lines(order["id"]):
        coupling = store.couplings[line["coupling_id"]]
        available = coupling["on_hand_qty"] - coupling_reserved_qty(coupling["id"])
        if line["quantity"] > available:
            raise ApiError(ERR_INSUFFICIENT_COUPLING_STOCK, 422,
                           "Line quantity exceeds coupling available_qty")
    # field shapes (priority 20), after every business rule has passed
    if waiver_by is not None and not isinstance(waiver_by, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "waiver_signed_by must be a string")
    if waiver_cents is not None and (isinstance(waiver_cents, bool)
                                     or not isinstance(waiver_cents, int)):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "waiver_liability_cents must be an integer")

    # cut-waste allocation (PRD §2.7): remnant of exactly zero is a clean
    # cut; below MIN_REMNANT_MM the whole remnant is scrapped and charged
    remaining_after = reel["remaining_length_mm"] - order["cut_length_mm"]
    if remaining_after == 0:
        scrap_added = 0
    elif remaining_after < MIN_REMNANT_MM:
        scrap_added = remaining_after
    else:
        scrap_added = 0
    reel["remaining_length_mm"] -= (order["cut_length_mm"] + scrap_added)
    reel["scrap_length_mm"] += scrap_added
    order["scrap_charged_mm"] = scrap_added
    order["waste_surcharge_cents"] = waste_surcharge_cents(scrap_added, reel)
    refresh_reel_status(reel)
    touch(reel)
    if waiver_by is not None and waiver_cents is not None:
        order["waiver_signed"] = True
        order["waiver_signed_by"] = waiver_by
        order["waiver_liability_cents"] = waiver_cents
    order["status"] = "CONFIRMED"
    touch(order)
    return success(serialize_order(order), status=200)


@bp.post("/api/assembly-orders/<oid>/complete-build")
def complete_build(oid):
    require_roles("ShopTechnician")
    order = _get_order(oid)
    _check_terminal(order)
    if order["status"] not in ("CONFIRMED", "REWORK"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Order is not CONFIRMED or REWORK")
    data = body()
    measured = get_num(data, "measured_crimp_diameter_mm")
    actual = get_int(data, "actual_labor_minutes")
    # crimp certification against the die-chart spec (Decimal avoids float
    # edge errors at the tolerance boundary)
    if (abs(Decimal(str(measured)) - Decimal(str(order["crimp_diameter_spec_mm"])))
            > Decimal(str(order["crimp_tolerance_mm"]))):
        raise ApiError(ERR_CRIMP_OUT_OF_TOLERANCE, 422,
                       "Measured crimp diameter outside spec +/- tolerance")
    order["measured_crimp_diameter_mm"] = measured
    order["actual_labor_minutes"] = actual
    order["status"] = "BUILT"
    touch(order)
    return success(serialize_order(order), status=200)


@bp.post("/api/assembly-orders/<oid>/record-pressure-test")
def record_pressure_test(oid):
    require_roles("ShopTechnician")
    order = _get_order(oid)
    _check_terminal(order)
    if order["status"] != "BUILT":
        raise ApiError(ERR_INVALID_STATE, 409, "Order is not BUILT")
    data = body()
    pressure = get_int(data, "test_pressure_psi")
    # the 2x multiple is enforced whether the recorded result is pass or fail
    if pressure < TEST_PRESSURE_MULTIPLIER * order["required_working_pressure_psi"]:
        raise ApiError(ERR_TEST_PRESSURE_TOO_LOW, 422,
                       "test_pressure_psi below 2.0x required working pressure")
    result = data.get("result")
    if result not in ("PASSED", "FAILED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "result must be PASSED or FAILED")
    order["test_pressure_psi"] = pressure
    order["test_result"] = result
    order["status"] = "TEST_PASSED" if result == "PASSED" else "TEST_FAILED"
    touch(order)
    return success(serialize_order(order), status=200)


@bp.post("/api/assembly-orders/<oid>/rework")
def rework_order(oid):
    require_roles("ShopTechnician")
    order = _get_order(oid)
    _check_terminal(order)
    if order["status"] != "TEST_FAILED":
        raise ApiError(ERR_INVALID_STATE, 409, "Order is not TEST_FAILED")
    # rework touches no inventory: the cut is already committed
    order["status"] = "REWORK"
    touch(order)
    return success(serialize_order(order), status=200)


@bp.post("/api/assembly-orders/<oid>/tag")
def tag_order(oid):
    require_roles("ShopTechnician")
    order = _get_order(oid)
    _check_terminal(order)
    if order["status"] != "TEST_PASSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Order is not TEST_PASSED")
    data = body()
    tag_serial = get_str(data, "tag_serial")
    # unique across every order that is not CANCELLED
    for other in store.orders.values():
        if (other["id"] != order["id"] and other["status"] != "CANCELLED"
                and other["tag_serial"] == tag_serial):
            raise ApiError(ERR_TAG_SERIAL_TAKEN, 409,
                           "tag_serial already present on another live order")
    order["tag_serial"] = tag_serial
    order["status"] = "TAGGED"
    touch(order)
    return success(serialize_order(order), status=200)


@bp.post("/api/assembly-orders/<oid>/complete")
def complete_order_endpoint(oid):
    require_roles(*COUNTER_ROLES)
    order = _get_order(oid)
    _check_terminal(order)
    if order["status"] != "TAGGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Order is not TAGGED")
    complete_order(order)
    return success(serialize_order(order), status=200)


@bp.post("/api/assembly-orders/<oid>/cancel")
def cancel_order(oid):
    require_roles(*COUNTER_ROLES)
    order = _get_order(oid)
    _check_terminal(order)
    # every non-terminal state is cancellable; restoration depends on how far
    # the order had progressed (PRD §3.5)
    if order["status"] == "CONFIRMED":
        # the reel is made whole: cut + scrap credited back
        reel = store.reels[order["reel_id"]]
        reel["remaining_length_mm"] += (order["cut_length_mm"]
                                        + order["scrap_charged_mm"])
        reel["scrap_length_mm"] -= order["scrap_charged_mm"]
        refresh_reel_status(reel)
        touch(reel)
    # from DRAFT nothing was committed; from BUILT/TEST_*/REWORK/TAGGED the
    # reel stays committed; coupling reservations release automatically with
    # the status change; a TAGGED cancel frees the tag serial for reuse
    # (uniqueness counts only non-CANCELLED orders)
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize_order(order), status=200)
