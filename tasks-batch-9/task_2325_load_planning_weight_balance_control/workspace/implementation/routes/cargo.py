"""Consignments, stowage and dangerous-goods declarations (PRD §3.4, §3.5)."""
from flask import Blueprint

import db
import middleware
import resolve
import response
import validate
from calc import D
from errors import (
    ERR_CARGO_INVALID_STATE,
    ERR_COMPARTMENT_KIND_MISMATCH,
    ERR_COMPARTMENT_NOT_ON_AIRCRAFT,
    ERR_DECLARATION_INVALID_STATE,
    ERR_DG_NOT_ACCEPTED,
    ERR_DG_QUANTITY_EXCEEDS_ITEM,
    ERR_DG_SEGREGATION_CONFLICT,
    ERR_DUPLICATE_KEY,
    ERR_FLIGHT_INVALID_STATE,
    ERR_NOT_DANGEROUS_GOODS,
    ERR_PLAN_INVALID_STATE,
    fail,
)
from middleware import ANY_ROLE, authorize
from services import balance

bp = Blueprint("cargo", __name__)

ITEM_KINDS = ("GENERAL", "MAIL", "COMPANY", "GATE_BAG")
CARGO_STATUSES = ("BOOKED", "ACCEPTED", "LOADED", "OFFLOADED", "DEFERRED", "REJECTED")
PRIORITY_RANK = {"COMPANY": 1, "GENERAL": 2, "MAIL": 3, "GATE_BAG": 4}

IMO_CLASSES = ("CLASS_1", "CLASS_2", "CLASS_3", "CLASS_5", "CLASS_8")
PACKING_GROUPS = ("I", "II", "III")
SEGREGATION_GROUPS = ("FLAMMABLE", "OXIDISER", "CORROSIVE", "INERT")
DECLARATION_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED")
INCOMPATIBLE = {"FLAMMABLE": "OXIDISER", "OXIDISER": "FLAMMABLE"}

DECLARABLE_CARGO_STATUSES = ("BOOKED", "ACCEPTED")


def _refresh_dg_hold(flight):
    """dg_hold_count is the number of SUBMITTED declarations on the flight's cargo."""
    held = 0
    for declaration in db.flight_declarations(flight["id"]):
        if declaration["status"] == "SUBMITTED":
            held += 1
    flight["dg_hold_count"] = held
    if held > 0:
        flight["load_release_state"] = "HELD_FOR_DG"
    elif flight["load_release_state"] == "HELD_FOR_DG":
        flight["load_release_state"] = "OPEN"
    db.touch(flight)


# ------------------------------------------------------------- consignments
@bp.post("/cargo-items")
@authorize("RampAgent")
def create_cargo_item():
    payload = validate.body()
    row = {
        "flight_id": validate.req_str(payload, "flight_id"),
        "awb_number": validate.req_str(payload, "awb_number"),
        "item_kind": validate.req_enum(payload, "item_kind", ITEM_KINDS),
        "weight_kg": validate.req_num(payload, "weight_kg", gt=0),
        "length_m": validate.req_num(payload, "length_m", gt=0),
        "is_dangerous_goods": validate.opt_bool(payload, "is_dangerous_goods", default=False),
        "assigned_compartment_id": None,
    }

    flight = resolve.flight(row["flight_id"])
    if any(item["awb_number"] == row["awb_number"] for item in db.flight_cargo(flight["id"])):
        fail(ERR_DUPLICATE_KEY, "That air waybill number is already booked on the flight.")
    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_FLIGHT_INVALID_STATE)

    row["offload_priority_rank"] = PRIORITY_RANK[row["item_kind"]]
    auto = row["item_kind"] != "GATE_BAG" and not row["is_dangerous_goods"]
    row["status"] = "ACCEPTED" if auto else "BOOKED"
    return response.object_response(db.public(db.insert(db.cargo_items, row)), 201)


@bp.get("/cargo-items/<row_id>")
@authorize(*ANY_ROLE)
def read_cargo_item(row_id):
    return response.object_response(db.public(resolve.cargo_item(row_id)))


@bp.get("/cargo-items")
@authorize(*ANY_ROLE)
def list_cargo_items():
    validate.pagination()
    flight_id = validate.query_str("flight_id")
    compartment_id = validate.query_str("assigned_compartment_id")
    status = validate.query_enum("status", CARGO_STATUSES)
    item_kind = validate.query_enum("item_kind", ITEM_KINDS)
    rows = []
    for item in db.cargo_items.values():
        if flight_id is not None and item["flight_id"] != flight_id:
            continue
        if compartment_id is not None and item.get("assigned_compartment_id") != compartment_id:
            continue
        if status is not None and item["status"] != status:
            continue
        if item_kind is not None and item["item_kind"] != item_kind:
            continue
        rows.append(item)
    items, meta = validate.paginate(db.ordered(rows))
    return response.list_response(items, meta)


@bp.post("/cargo-items/<row_id>/assign")
@authorize("RampAgent", "LoadController")
def assign_cargo_item(row_id):
    payload = validate.body()
    compartment_id = validate.req_str(payload, "assigned_compartment_id")

    item = resolve.cargo_item(row_id)
    compartment = resolve.compartment(compartment_id)
    flight = db.flights[item["flight_id"]]

    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_FLIGHT_INVALID_STATE)

    plans = balance.active_plans(flight["id"])
    for plan in plans:
        if balance.sheets_freeze_plan(plan["id"]):
            fail(ERR_PLAN_INVALID_STATE, "The distribution is frozen by an issued load sheet.")

    if item["status"] not in ("BOOKED", "ACCEPTED", "LOADED"):
        fail(ERR_CARGO_INVALID_STATE)
    if compartment["aircraft_id"] != flight["aircraft_id"]:
        fail(ERR_COMPARTMENT_NOT_ON_AIRCRAFT)
    if compartment["kind"] != "HOLD":
        fail(ERR_COMPARTMENT_KIND_MISMATCH)

    # PRD §3.4: the two ceilings are re-evaluated "with this consignment included",
    # so its own mass counts once whatever status it is stowed from.
    occupancy = balance.hold_occupancy(flight["id"], compartment_id, exclude_cargo_id=item["id"])
    balance.check_hold_ceilings(compartment, occupancy + D(item["weight_kg"]))

    item["assigned_compartment_id"] = compartment_id
    db.touch(item)
    for plan in plans:
        balance.invalidate_computation(flight, plan)
    return response.object_response(db.public(item))


@bp.post("/cargo-items/<row_id>/accept")
@authorize("RampAgent")
def accept_cargo_item(row_id):
    item = resolve.cargo_item(row_id)
    flight = db.flights[item["flight_id"]]
    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_FLIGHT_INVALID_STATE)
    if item["status"] != "BOOKED":
        fail(ERR_CARGO_INVALID_STATE)
    if item["is_dangerous_goods"]:
        accepted = any(
            d["status"] == "ACCEPTED" for d in db.cargo_declarations(item["id"])
        )
        if not accepted:
            fail(ERR_DG_NOT_ACCEPTED)

    item["status"] = "ACCEPTED"
    db.touch(item)
    return response.object_response(db.public(item))


@bp.post("/cargo-items/<row_id>/reject")
@authorize("RampAgent")
def reject_cargo_item(row_id):
    item = resolve.cargo_item(row_id)
    if item["status"] != "BOOKED":
        fail(ERR_CARGO_INVALID_STATE)
    item["status"] = "REJECTED"
    item["assigned_compartment_id"] = None
    db.touch(item)
    return response.object_response(db.public(item))


# -------------------------------------------------------------- declarations
@bp.post("/hazmat-declarations")
@authorize("RampAgent")
def create_declaration():
    payload = validate.body()
    row = {
        "cargo_item_id": validate.req_str(payload, "cargo_item_id"),
        "un_number": validate.req_str(payload, "un_number"),
        "imo_class": validate.req_enum(payload, "imo_class", IMO_CLASSES),
        "packing_group": validate.req_enum(payload, "packing_group", PACKING_GROUPS),
        "segregation_group": validate.req_enum(payload, "segregation_group", SEGREGATION_GROUPS),
        "quantity_kg": validate.req_num(payload, "quantity_kg", ge=0),
        "status": "SUBMITTED",
        "accepted_by_user_id": None,
        "notoc_issued": False,
    }

    item = resolve.cargo_item(row["cargo_item_id"])
    flight = db.flights[item["flight_id"]]

    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_CARGO_INVALID_STATE, "The flight no longer accepts dangerous-goods declarations.")
    if item["status"] not in DECLARABLE_CARGO_STATUSES:
        fail(ERR_CARGO_INVALID_STATE)
    if not item["is_dangerous_goods"]:
        fail(ERR_NOT_DANGEROUS_GOODS)
    if D(row["quantity_kg"]) > D(item["weight_kg"]):
        fail(ERR_DG_QUANTITY_EXCEEDS_ITEM)

    declaration = db.insert(db.hazmat_declarations, row)
    _refresh_dg_hold(flight)
    return response.object_response(db.public(declaration), 201)


@bp.get("/hazmat-declarations/<row_id>")
@authorize(*ANY_ROLE)
def read_declaration(row_id):
    return response.object_response(db.public(resolve.declaration(row_id)))


@bp.get("/cargo-items/<row_id>/hazmat-declarations")
@authorize(*ANY_ROLE)
def list_cargo_declarations(row_id):
    validate.pagination()
    status = validate.query_enum("status", DECLARATION_STATUSES)
    resolve.cargo_item(row_id)
    rows = [
        d
        for d in db.cargo_declarations(row_id)
        if status is None or d["status"] == status
    ]
    items, meta = validate.paginate(rows)
    return response.list_response(items, meta)


@bp.post("/hazmat-declarations/<row_id>/accept")
@authorize("DangerousGoodsOfficer")
def accept_declaration(row_id):
    declaration = resolve.declaration(row_id)
    item = db.cargo_items[declaration["cargo_item_id"]]
    flight = db.flights[item["flight_id"]]

    if declaration["status"] != "SUBMITTED":
        fail(ERR_DECLARATION_INVALID_STATE)
    if item["status"] not in DECLARABLE_CARGO_STATUSES:
        fail(ERR_CARGO_INVALID_STATE)

    forbidden = INCOMPATIBLE.get(declaration["segregation_group"])
    hold = item.get("assigned_compartment_id")
    if forbidden is not None and hold:
        for other in db.flight_cargo(flight["id"]):
            if other["id"] == item["id"]:
                continue
            if other.get("assigned_compartment_id") != hold:
                continue
            for peer in db.cargo_declarations(other["id"]):
                if peer["status"] == "ACCEPTED" and peer["segregation_group"] == forbidden:
                    fail(ERR_DG_SEGREGATION_CONFLICT)

    declaration["status"] = "ACCEPTED"
    declaration["accepted_by_user_id"] = middleware.current_user_id()
    db.touch(declaration)
    _refresh_dg_hold(flight)
    return response.object_response(db.public(declaration))


@bp.post("/hazmat-declarations/<row_id>/reject")
@authorize("DangerousGoodsOfficer")
def reject_declaration(row_id):
    declaration = resolve.declaration(row_id)
    item = db.cargo_items[declaration["cargo_item_id"]]
    flight = db.flights[item["flight_id"]]

    if declaration["status"] != "SUBMITTED":
        fail(ERR_DECLARATION_INVALID_STATE)

    declaration["status"] = "REJECTED"
    db.touch(declaration)
    if item["status"] == "BOOKED":
        item["status"] = "REJECTED"
        item["assigned_compartment_id"] = None
        db.touch(item)
    _refresh_dg_hold(flight)
    return response.object_response(db.public(declaration))
