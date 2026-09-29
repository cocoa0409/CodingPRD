"""Part lots, stock adjustments and parts reservations."""

from flask import Blueprint

import calc
import services as svc
from core import (
    db, fail, get_body, iso, new_row, now, ordered, page, pagination, q_str,
    require, respond, respond_list, set_fields, v_bool, v_enum, v_int, v_string,
)

bp = Blueprint("parts", __name__)

LOT_STATES = ("AVAILABLE", "LOW", "DEPLETED")
RESERVATION_STATES = ("RESERVED", "CONSUMED", "RELEASED")


# --------------------------------------------------------------------------- #
# Part lots
# --------------------------------------------------------------------------- #

@bp.post("/part-lots")
def create_lot():
    require("PartsCoordinator", "ProgramAdmin")
    body = get_body()
    model = svc.fk(body, "gear_model_id", db.gear_models, "ERR_GEAR_MODEL_NOT_FOUND")
    if model is None:
        fail("ERR_INVALID_REQUEST", "Field 'gear_model_id' is required.")
    part_code = v_string(body, "part_code", required=True, min_len=3, max_len=40)
    part_kind = v_enum(body, "part_kind", calc.PART_KINDS, required=True)
    on_hand = v_int(body, "on_hand_units", required=True, min_value=0)
    unit_price = v_int(body, "unit_price_cents", required=True, min_value=0)
    watermark = v_int(body, "low_watermark_units", min_value=0, default=2)
    substitution_allowed = v_bool(body, "substitution_allowed", default=False)
    substitute_for = v_string(body, "substitute_for_part_code", min_len=1, max_len=40)

    for existing in db.part_lots.values():
        if existing["gear_model_id"] == model["id"] and existing["part_code"] == part_code:
            fail("ERR_PART_CODE_TAKEN")

    if not substitution_allowed:
        substitute_for = None

    row = new_row()
    row.update({
        "gear_model_id": model["id"],
        "part_code": part_code,
        "part_kind": part_kind,
        "on_hand_units": on_hand,
        "reserved_units": 0,
        "available_units": on_hand,
        "unit_price_cents": unit_price,
        "low_watermark_units": watermark,
        "status": calc.lot_status(on_hand, watermark),
        "substitution_allowed": substitution_allowed,
        "substitute_for_part_code": substitute_for,
    })
    db.part_lots[row["id"]] = row
    svc.recompute_support_for_lot(row)
    return respond(svc.ser(row), 201)


@bp.get("/part-lots/<lot_id>")
def read_lot(lot_id):
    require("ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    lot = svc.need(db.part_lots, lot_id, "ERR_PART_LOT_NOT_FOUND")
    return respond(svc.ser(lot))


@bp.get("/part-lots")
def list_lots():
    require("ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    model_id = q_str("gear_model_id")
    part_kind = q_str("part_kind")
    if part_kind is not None and part_kind not in calc.PART_KINDS:
        fail("ERR_INVALID_REQUEST", "Query parameter 'part_kind' is not a recognised value.")
    status = q_str("status")
    if status is not None and status not in LOT_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    limit, offset = pagination()

    rows = []
    for lot in ordered(db.part_lots):
        if model_id is not None and lot["gear_model_id"] != model_id:
            continue
        if part_kind is not None and lot["part_kind"] != part_kind:
            continue
        if status is not None and lot["status"] != status:
            continue
        rows.append(lot)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


@bp.post("/part-lots/<lot_id>/adjustments")
def adjust_lot(lot_id):
    require("PartsCoordinator", "ProgramAdmin")
    lot = svc.need(db.part_lots, lot_id, "ERR_PART_LOT_NOT_FOUND")
    body = get_body()
    if "delta_units" not in body or body["delta_units"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'delta_units' is required.")
    delta = body["delta_units"]
    if isinstance(delta, bool) or not isinstance(delta, int):
        fail("ERR_INVALID_REQUEST", "Field 'delta_units' must be an integer.")
    reason = v_string(body, "reason", required=True, min_len=1, max_len=500)

    # check 42 -- a zero adjustment is meaningless
    if delta == 0:
        fail("ERR_INVALID_UNITS")
    # check 44 -- never below what is already reserved
    if lot["on_hand_units"] + delta < lot["reserved_units"]:
        fail("ERR_INSUFFICIENT_STOCK_ADJUSTMENT")

    set_fields(lot, on_hand_units=lot["on_hand_units"] + delta)
    svc.recompute_lot(lot)
    return respond(svc.ser(lot))


# --------------------------------------------------------------------------- #
# Parts reservations
# --------------------------------------------------------------------------- #

@bp.post("/repair-orders/<order_id>/parts-reservations")
def create_reservation(order_id):
    require("RepairTechnician", "PartsCoordinator")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    body = get_body()

    # check 8 -- second-level reference
    lot = svc.fk(body, "part_lot_id", db.part_lots, "ERR_PART_LOT_NOT_FOUND")

    # check 9 -- shape (units bounds are check 42, deliberately not here)
    if lot is None:
        fail("ERR_INVALID_REQUEST", "Field 'part_lot_id' is required.")
    required_part_code = v_string(body, "required_part_code", required=True, min_len=1, max_len=40)
    units = v_int(body, "units", required=True)

    # check 12 -- the order's bench dimension must accept parts
    if order["work_status"] not in calc.QUEUE_STATES:
        fail("ERR_INVALID_WORK_STATE")

    item = db.gear_items.get(order["gear_item_id"])
    model = svc.model_of_item(item) if item is not None else None
    model_id = model["id"] if model is not None else None
    successor_id = model.get("successor_model_id") if model is not None else None

    is_substitution = lot["part_code"] != required_part_code
    if not is_substitution:
        # check 26 -- exact-code draw must come from the order's own model
        if lot["gear_model_id"] != model_id:
            fail("ERR_PART_MODEL_MISMATCH")
    else:
        # check 26 -- substitution draw may come from the model or its successor
        if lot["gear_model_id"] not in (model_id, successor_id) or lot["gear_model_id"] is None:
            fail("ERR_PART_MODEL_MISMATCH")
        # check 27 -- substitution eligibility
        if not lot["substitution_allowed"]:
            fail("ERR_SUBSTITUTION_NOT_PERMITTED")
        if lot["substitute_for_part_code"] != required_part_code:
            fail("ERR_SUBSTITUTION_NOT_PERMITTED")
        reference_kinds = set()
        for candidate in db.part_lots.values():
            if (
                candidate["part_code"] == required_part_code
                and candidate["gear_model_id"] in (model_id, successor_id)
            ):
                reference_kinds.add(candidate["part_kind"])
        if lot["part_kind"] not in reference_kinds:
            fail("ERR_SUBSTITUTION_NOT_PERMITTED")

    # check 42 -- at least one unit
    if units < 1:
        fail("ERR_INVALID_UNITS")
    # check 43 -- never more than is available
    if units > lot["available_units"]:
        fail("ERR_INSUFFICIENT_PART_UNITS")

    row = new_row()
    row.update({
        "repair_order_id": order["id"],
        "part_lot_id": lot["id"],
        "required_part_code": required_part_code,
        "units": units,
        "is_substitution": is_substitution,
        "status": "RESERVED",
        "settled_at": None,
    })
    db.parts_reservations[row["id"]] = row

    set_fields(lot, reserved_units=lot["reserved_units"] + units)
    svc.recompute_lot(lot)
    return respond(svc.ser(row), 201)


@bp.get("/parts-reservations/<reservation_id>")
def read_reservation(reservation_id):
    require("ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    reservation = svc.need(db.parts_reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    return respond(svc.ser(reservation))


@bp.get("/parts-reservations")
def list_reservations():
    require("ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    order_id = q_str("repair_order_id")
    lot_id = q_str("part_lot_id")
    status = q_str("status")
    if status is not None and status not in RESERVATION_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    limit, offset = pagination()

    rows = []
    for reservation in ordered(db.parts_reservations):
        if order_id is not None and reservation["repair_order_id"] != order_id:
            continue
        if lot_id is not None and reservation["part_lot_id"] != lot_id:
            continue
        if status is not None and reservation["status"] != status:
            continue
        rows.append(reservation)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


@bp.post("/parts-reservations/<reservation_id>/release")
def release(reservation_id):
    require("PartsCoordinator")
    reservation = svc.need(db.parts_reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    body = get_body()
    v_string(body, "reason", max_len=500)

    # check 15
    if reservation["status"] != "RESERVED":
        fail("ERR_RESERVATION_NOT_RESERVED")

    svc.release_reservation(reservation)
    return respond(svc.ser(reservation))


@bp.post("/parts-reservations/<reservation_id>/consume")
def consume(reservation_id):
    require("RepairTechnician")
    reservation = svc.need(db.parts_reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    order = db.repair_orders.get(reservation["repair_order_id"])

    # check 12 then check 15
    if order is not None and order["work_status"] not in calc.QUEUE_STATES:
        fail("ERR_INVALID_WORK_STATE")
    if reservation["status"] != "RESERVED":
        fail("ERR_RESERVATION_NOT_RESERVED")

    svc.consume_reservation(reservation)
    return respond(svc.ser(reservation))
