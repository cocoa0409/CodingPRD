"""InventoryLot and MaterialReservation endpoints (the conservation ledger)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INSUFFICIENT_INVENTORY,
    ERR_RESERVATION_KIND_MISMATCH,
    ERR_STALE_LOT_VERSION,
)
from middleware import authenticate, require_role, get_or_404, INTERNAL_ROLES
from response import success, success_list
from services import cascade, serializers
from util import as_enum, as_int, as_num, as_str, as_fk, body, paginate

bp = Blueprint("inventory", __name__)

LOT_KINDS = {"LUMBER", "PLATE"}
DIMENSIONS = {"L2X4", "L2X6", "L2X8"}
LUMBER_GRADES = {"SPF_NO2", "SPF_MSR2400", "SYP_NO1"}
PLATE_CLASSES = {"P20", "P18", "P16"}
LOT_STATES = {"ACTIVE", "QUARANTINED", "DEPLETED"}


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------

@bp.route("/plant/inventory-lots", methods=["POST"])
def create_lot():
    _uid, role = authenticate()
    require_role(role, ["InventoryManager"])
    data = body()
    lot_kind = as_enum(data.get("lot_kind"), "lot_kind", LOT_KINDS, required=True)
    lumber_dimension = data.get("lumber_dimension")
    lumber_grade = data.get("lumber_grade")
    plate_class = data.get("plate_class")
    received_board_feet = as_num(data.get("received_board_feet"), "received_board_feet", default=Decimal("0"))
    received_plates = as_int(data.get("received_plates"), "received_plates", default=0)
    # Conditional input rules (section 2.7): lumber attributes iff LUMBER,
    # plate attributes iff PLATE; plate lots must report 0 bf and lumber lots
    # 0 plates.
    if lot_kind == "LUMBER":
        lumber_dimension = as_enum(lumber_dimension, "lumber_dimension", DIMENSIONS, required=True)
        lumber_grade = as_enum(lumber_grade, "lumber_grade", LUMBER_GRADES, required=True)
        if plate_class is not None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "plate_class must be null for LUMBER lots")
        if received_plates != 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "received_plates must be 0 for LUMBER lots")
    else:
        plate_class = as_enum(plate_class, "plate_class", PLATE_CLASSES, required=True)
        if lumber_dimension is not None or lumber_grade is not None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "lumber attributes must be null for PLATE lots")
        if received_board_feet != 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "received_board_feet must be 0 for PLATE lots")
    rec = db.new_record({
        "lot_kind": lot_kind,
        "lumber_dimension": lumber_dimension,
        "lumber_grade": lumber_grade,
        "plate_class": plate_class,
        "received_board_feet": received_board_feet,
        "received_plates": received_plates,
        "unit_cost_cents_per_bf": as_int(data.get("unit_cost_cents_per_bf"), "unit_cost_cents_per_bf", default=0),
        "unit_cost_cents_per_plate": as_int(data.get("unit_cost_cents_per_plate"), "unit_cost_cents_per_plate", default=0),
        "available_bf": received_board_feet,
        "reserved_bf": Decimal("0"),
        "consumed_bf": Decimal("0"),
        "scrapped_bf": Decimal("0"),
        "available_plates": received_plates,
        "reserved_plates": 0,
        "consumed_plates": 0,
        "scrapped_plates": 0,
        "status": "ACTIVE",
    })
    db.inventory_lots[rec["id"]] = rec
    return success(serializers.inventory_lot(rec), status=201)


@bp.route("/plant/inventory-lots/<lid>", methods=["GET"])
def get_lot(lid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.inventory_lot(get_or_404(db.inventory_lots, lid, "inventory lot")))


@bp.route("/plant/inventory-lots", methods=["GET"])
def list_lots():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.inventory_lots.values())
    for field in ("lot_kind", "status", "lumber_dimension", "lumber_grade"):
        raw = request.args.get(field)
        if raw is not None:
            records = [l for l in records if l[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.inventory_lot(l) for l in page], meta)


@bp.route("/plant/inventory-lots/<lid>/adjust", methods=["POST"])
def adjust_lot(lid):
    _uid, role = authenticate()
    require_role(role, ["InventoryManager"])
    rec = get_or_404(db.inventory_lots, lid, "inventory lot")
    data = body()
    as_str(data.get("reason"), "reason", required=True)
    rec["available_bf"] += as_num(data.get("adjust_available_bf"), "adjust_available_bf", default=Decimal("0"))
    rec["scrapped_bf"] += as_num(data.get("adjust_scrapped_bf"), "adjust_scrapped_bf", default=Decimal("0"))
    rec["available_plates"] += as_int(data.get("adjust_available_plates"), "adjust_available_plates", default=0)
    rec["scrapped_plates"] += as_int(data.get("adjust_scrapped_plates"), "adjust_scrapped_plates", default=0)
    db.touch(rec)
    cascade.lot_depleted_recheck(rec)
    return success(serializers.inventory_lot(rec))


@bp.route("/plant/inventory-lots/<lid>/transition", methods=["POST"])
def lot_transition(lid):
    _uid, role = authenticate()
    require_role(role, ["InventoryManager"])
    rec = get_or_404(db.inventory_lots, lid, "inventory lot")
    data = body()
    to_state = as_enum(data.get("to_state"), "to_state", LOT_STATES, required=True)
    if (rec["status"], to_state) not in (("ACTIVE", "QUARANTINED"), ("QUARANTINED", "ACTIVE")):
        raise ApiError(ERR_INVALID_STATE, 409, f"lot transition {rec['status']} -> {to_state} is not declared")
    rec["status"] = to_state
    db.touch(rec)
    return success(serializers.inventory_lot(rec))


# ---------------------------------------------------------------------------
# Material reservations (OCC-guarded on the lot's version)
# ---------------------------------------------------------------------------

@bp.route("/plant/material-reservations", methods=["POST"])
def create_reservation():
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    data = body()
    # Existence: body FKs in declared input order.
    lot = as_fk(data.get("lot_id"), "lot_id", db.inventory_lots, "inventory lot")
    line = as_fk(data.get("cut_list_line_id"), "cut_list_line_id", db.cut_list_lines, "cut list line")
    cut_list = as_fk(data.get("cut_list_id"), "cut_list_id", db.cut_lists, "cut list")
    # Schema.
    if lot is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: lot_id")
    expected_lot_version = as_int(data.get("expected_lot_version"), "expected_lot_version", required=True)
    if line is not None and cut_list is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "a reservation carries exactly one of cut_list_line_id and cut_list_id")
    if line is None and cut_list is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "a reservation carries exactly one of cut_list_line_id and cut_list_id")
    reserved_bf = as_num(data.get("reserved_bf"), "reserved_bf", default=Decimal("0"))
    reserved_plates = as_int(data.get("reserved_plates"), "reserved_plates", default=0)
    # OCC (priority 6).
    if expected_lot_version != lot["version"]:
        raise ApiError(ERR_STALE_LOT_VERSION, 412, "lot version has advanced since last read")
    # Kind/target match (priority 25) precedes availability (priority 26).
    if lot["lot_kind"] == "LUMBER":
        if reserved_plates != 0 or reserved_bf <= 0:
            raise ApiError(ERR_RESERVATION_KIND_MISMATCH, 422,
                           "a LUMBER reservation requires reserved_bf > 0 and reserved_plates == 0")
        if cut_list is not None:
            raise ApiError(ERR_RESERVATION_KIND_MISMATCH, 422,
                           "cut_list_id must be null for LUMBER reservations")
        if line is not None:
            line_list = db.cut_lists[line["cut_list_id"]]
            line_design = db.designs[line_list["design_id"]]
            if lot["lumber_dimension"] != line["dimension"] or lot["lumber_grade"] != line_design["lumber_grade"]:
                raise ApiError(ERR_RESERVATION_KIND_MISMATCH, 422,
                               "lot dimension/grade must equal the line dimension and design grade")
            if line["status"] == "SCRAPPED":
                raise ApiError(ERR_RESERVATION_KIND_MISMATCH, 422, "line is already terminal")
    else:  # PLATE
        if reserved_bf != 0 or reserved_plates <= 0:
            raise ApiError(ERR_RESERVATION_KIND_MISMATCH, 422,
                           "a PLATE reservation requires reserved_plates > 0 and reserved_bf == 0")
        if line is not None:
            raise ApiError(ERR_RESERVATION_KIND_MISMATCH, 422,
                           "cut_list_line_id must be null for PLATE reservations")
        if cut_list is not None:
            list_design = db.designs[cut_list["design_id"]]
            if lot["plate_class"] != list_design["plating"]:
                raise ApiError(ERR_RESERVATION_KIND_MISMATCH, 422,
                               "lot plate_class must equal the design plating")
    # Availability (priority 26).
    if lot["status"] != "ACTIVE":
        raise ApiError(ERR_INSUFFICIENT_INVENTORY, 422, "lot is not ACTIVE")
    if lot["lot_kind"] == "LUMBER":
        if reserved_bf > lot["available_bf"]:
            raise ApiError(ERR_INSUFFICIENT_INVENTORY, 422, "reserved_bf exceeds lot availability")
    else:
        if reserved_plates > lot["available_plates"]:
            raise ApiError(ERR_INSUFFICIENT_INVENTORY, 422, "reserved_plates exceeds lot availability")
    rec = db.new_record({
        "lot_id": lot["id"],
        "cut_list_line_id": line["id"] if line else None,
        "cut_list_id": cut_list["id"] if cut_list else None,
        "reserved_bf": reserved_bf,
        "reserved_plates": reserved_plates,
        "status": "RESERVED",
    })
    db.material_reservations[rec["id"]] = rec
    cascade.reservation_reserve_apply(rec)
    return success(serializers.material_reservation(rec), status=201)


@bp.route("/plant/material-reservations", methods=["GET"])
def list_reservations():
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    records = list(db.material_reservations.values())
    for field in ("lot_id", "cut_list_line_id", "cut_list_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [r for r in records if r[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.material_reservation(r) for r in page], meta)


@bp.route("/plant/material-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    _uid, role = authenticate()
    require_role(role, INTERNAL_ROLES)
    return success(serializers.material_reservation(
        get_or_404(db.material_reservations, rid, "material reservation")))


@bp.route("/plant/material-reservations/<rid>/consume", methods=["POST"])
def consume_reservation(rid):
    _uid, role = authenticate()
    require_role(role, ["InventoryManager"])
    rec = get_or_404(db.material_reservations, rid, "material reservation")
    if rec["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, 409, f"reservation in status {rec['status']} cannot be consumed")
    lot = db.inventory_lots[rec["lot_id"]]
    if lot["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "lot is not ACTIVE")
    cascade.reservation_consume_apply(rec)
    return success(serializers.material_reservation(rec))


@bp.route("/plant/material-reservations/<rid>/release", methods=["POST"])
def release_reservation(rid):
    _uid, role = authenticate()
    require_role(role, ["InventoryManager"])
    rec = get_or_404(db.material_reservations, rid, "material reservation")
    if rec["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, 409, f"reservation in status {rec['status']} cannot be released")
    cascade.reservation_release_apply(rec)
    return success(serializers.material_reservation(rec))
