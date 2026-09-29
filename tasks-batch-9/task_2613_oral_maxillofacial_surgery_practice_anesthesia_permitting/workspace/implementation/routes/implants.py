"""Implant lots, reservations, auto-sizing and consignment exposure."""
from flask import Blueprint

from db import db, new_record, ordered, touch
from errors import ApiError
from middleware import authorize
from routes.helpers import ALL_ROLES, scope_check, send, send_list
from services.domain import (LOT_STATUSES, RESERVATION_STATUSES,
                             SELECTION_MODES, get_case, get_lot, get_practice,
                             path_row, referenced_row, reservations_of_lot)
from services.inventory import (auto_size_select, consume_reservation,
                                credit_limit_check, hold_pricing,
                                recompute_lot, release_reservation,
                                short_reservation)
from services.practice import recompute_consignment, touch_practice
from timeutil import parse_date
from validation import (q_bool, q_enum, q_string, read_body, v_enum, v_id,
                        v_instant, v_int, v_number, v_string)

bp = Blueprint("implants", __name__)


@bp.post("/implant-lots")
def create_lot():
    authorize("InventoryManager")
    body = read_body(
        required=("practice_id", "manufacturer_code", "catalog_reference",
                  "diameter_mm", "length_mm", "unit_cost_cents",
                  "quantity_on_hand", "expiry_date"),
        optional=("is_consignment",),
    )
    practice_id = v_id(body, "practice_id")
    manufacturer_code = v_string(body, "manufacturer_code", min_len=1, max_len=32)
    catalog_reference = v_string(body, "catalog_reference", min_len=1, max_len=64)
    diameter_mm = v_number(body, "diameter_mm", exclusive_min=0)
    length_mm = v_number(body, "length_mm", exclusive_min=0)
    unit_cost_cents = v_int(body, "unit_cost_cents", minimum=0)
    quantity_on_hand = v_int(body, "quantity_on_hand", minimum=0)
    expiry_date = v_instant(body, "expiry_date")
    is_consignment = body.get("is_consignment", False)
    if not isinstance(is_consignment, bool):
        raise ApiError("ERR_INVALID_FIELD_VALUE", "Field 'is_consignment' must be a boolean.")

    referenced_row(db.practices, practice_id)

    lot = new_record({
        "practice_id": practice_id,
        "manufacturer_code": manufacturer_code,
        "catalog_reference": catalog_reference,
        "diameter_mm": diameter_mm,
        "length_mm": length_mm,
        "is_consignment": is_consignment,
        "unit_cost_cents": unit_cost_cents,
        "quantity_on_hand": quantity_on_hand,
        "expiry_date": expiry_date,
        "quantity_reserved": 0,
        "available_quantity": quantity_on_hand,
        "status": "AVAILABLE",
    })
    db.lots[lot["id"]] = lot
    return send(lot, 201)


@bp.get("/implant-lots/<lot_id>")
def read_lot(lot_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.lots, lot_id))


@bp.get("/implant-lots")
def list_lots():
    authorize(*ALL_ROLES)
    practice_id = q_string("practice_id")
    manufacturer_code = q_string("manufacturer_code")
    is_consignment = q_bool("is_consignment")
    status = q_enum("status", LOT_STATUSES)
    rows = ordered([l for l in db.lots.values()
                    if (practice_id is None or l["practice_id"] == practice_id)
                    and (manufacturer_code is None or l["manufacturer_code"] == manufacturer_code)
                    and (is_consignment is None or bool(l["is_consignment"]) == is_consignment)
                    and (status is None or l["status"] == status)])
    return send_list(rows)


@bp.post("/implant-lots/<lot_id>/quarantine")
def quarantine_lot(lot_id):
    authorize("InventoryManager")
    lot = path_row(db.lots, lot_id)
    body = read_body(required=("quarantine_reason",))
    v_string(body, "quarantine_reason", min_len=1, max_len=240)

    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    lot["status"] = "QUARANTINED"
    for reservation in reservations_of_lot(lot["id"]):
        if reservation["status"] == "HELD":
            release_reservation(reservation, waive_fee=True)
    recompute_lot(lot)
    lot["available_quantity"] = 0
    touch(lot)
    practice = get_practice(lot["practice_id"])
    if practice is not None:
        recompute_consignment(practice)
        touch_practice(practice)
    return send(lot)


def _persist_reservation(case, lot, quantity, selection_mode,
                         requested_diameter_mm=None, requested_length_mm=None):
    pricing = hold_pricing(lot, quantity)
    practice = get_practice(case["practice_id"])
    credit_limit_check(practice, pricing["consignment_liability_cents"])

    reservation = new_record({
        "case_id": case["id"],
        "lot_id": lot["id"],
        "quantity": quantity,
        "requested_diameter_mm": requested_diameter_mm,
        "requested_length_mm": requested_length_mm,
        "selection_mode": selection_mode,
        "status": "HELD",
        "line_subtotal_cents": pricing["line_subtotal_cents"],
        "restocking_fee_cents": pricing["restocking_fee_cents"],
        "consignment_credit_cents": pricing["consignment_credit_cents"],
        "consignment_liability_cents": pricing["consignment_liability_cents"],
    })
    db.reservations[reservation["id"]] = reservation
    recompute_lot(lot)
    touch(lot)
    recompute_consignment(practice)
    touch_practice(practice)
    return reservation


@bp.post("/implant-reservations")
def create_reservation():
    authorize("InventoryManager")
    body = read_body(required=("case_id", "lot_id", "quantity", "expected_lot_version"))
    case_id = v_id(body, "case_id")
    lot_id = v_id(body, "lot_id")
    quantity = v_int(body, "quantity", minimum=1)
    expected_lot_version = v_int(body, "expected_lot_version", minimum=0)

    case = referenced_row(db.cases, case_id)
    lot = referenced_row(db.lots, lot_id)
    scope_check(lot["practice_id"], case["practice_id"])

    if int(lot["version"]) != expected_lot_version:
        raise ApiError("ERR_STALE_LOT_VERSION")
    if lot["status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_UNAVAILABLE")
    recompute_lot(lot)
    expiry = parse_date(lot["expiry_date"])
    if int(lot["available_quantity"]) < quantity or expiry <= parse_date(case["planned_start"]):
        raise ApiError("ERR_IMPLANT_STOCK_INSUFFICIENT")

    reservation = _persist_reservation(case, lot, quantity, "EXPLICIT")
    return send(reservation, 201)


@bp.post("/surgical-cases/<case_id>/implant-reservations/auto-size")
def auto_size_reservation(case_id):
    authorize("InventoryManager")
    case = path_row(db.cases, case_id)
    body = read_body(required=("requested_diameter_mm", "requested_length_mm", "quantity"))
    requested_diameter_mm = v_number(body, "requested_diameter_mm", exclusive_min=0)
    requested_length_mm = v_number(body, "requested_length_mm", exclusive_min=0)
    quantity = v_int(body, "quantity", minimum=1)

    for lot in db.lots.values():
        if lot["practice_id"] == case["practice_id"]:
            recompute_lot(lot)
    lot = auto_size_select(case, requested_diameter_mm, requested_length_mm, quantity)
    reservation = _persist_reservation(case, lot, quantity, "AUTO_SIZED",
                                       requested_diameter_mm, requested_length_mm)
    return send(reservation, 201)


@bp.get("/implant-reservations/<reservation_id>")
def read_reservation(reservation_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.reservations, reservation_id))


@bp.get("/implant-reservations")
def list_reservations():
    authorize(*ALL_ROLES)
    case_id = q_string("case_id")
    lot_id = q_string("lot_id")
    selection_mode = q_enum("selection_mode", SELECTION_MODES)
    status = q_enum("status", RESERVATION_STATUSES)
    rows = ordered([r for r in db.reservations.values()
                    if (case_id is None or r["case_id"] == case_id)
                    and (lot_id is None or r["lot_id"] == lot_id)
                    and (selection_mode is None or r["selection_mode"] == selection_mode)
                    and (status is None or r["status"] == status)])
    return send_list(rows)


@bp.post("/implant-reservations/<reservation_id>/consume")
def consume(reservation_id):
    authorize("InventoryManager")
    reservation = path_row(db.reservations, reservation_id)
    case = get_case(reservation["case_id"])
    lot = get_lot(reservation["lot_id"])

    if reservation["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if case is None or case["scheduling_status"] not in ("CONFIRMED", "IN_RECOVERY"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if lot is None or lot["status"] != "AVAILABLE":
        raise ApiError("ERR_LOT_UNAVAILABLE")

    consume_reservation(reservation)
    practice = get_practice(case["practice_id"])
    if practice is not None:
        recompute_consignment(practice)
        touch_practice(practice)
    return send(reservation)


@bp.post("/implant-reservations/<reservation_id>/release")
def release(reservation_id):
    authorize("InventoryManager")
    reservation = path_row(db.reservations, reservation_id)
    body = read_body(required=("disposition",))
    disposition = v_enum(body, "disposition", ("RELEASED", "SHORTED"))

    if reservation["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if disposition == "RELEASED":
        release_reservation(reservation)
    else:
        short_reservation(reservation)
    case = get_case(reservation["case_id"])
    practice = get_practice(case["practice_id"]) if case is not None else None
    if practice is not None:
        recompute_consignment(practice)
        touch_practice(practice)
    return send(reservation)
