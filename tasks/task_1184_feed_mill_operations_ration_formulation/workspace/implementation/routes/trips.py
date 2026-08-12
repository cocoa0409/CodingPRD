"""Delivery trips: dispatch window rules, compartment allocation, and the
delivery chain that can bubble an order to DELIVERED (PRD 3.9)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import STORE, make_record, bump
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import (ser_trip, sorted_items, order_blocked, truck_window_conflict,
                      maybe_bubble_order_delivered)
from validation import get_body, field, req_str, req_enum, req_dt, req_num, bad, paginate, MISSING

bp = Blueprint("trips", __name__)


def _get_trip_scoped(tid, role, uid):
    t = STORE["trips"].get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Trip {tid} not found")
    if role == "Customer":
        order = STORE["orders"].get(t["order_id"])
        if order is None or order["customer_id"] != uid:
            raise ApiError("ERR_NOT_FOUND", 404, f"Trip {tid} not found")
    return t


def parse_allocations(data):
    allocs = field(data, "compartment_allocations")
    if not isinstance(allocs, list):
        bad("compartment_allocations must be a list")
    parsed = []
    for entry in allocs:
        if not isinstance(entry, dict):
            bad("Each compartment allocation must be an object")
        seq = entry.get("compartment_seq", MISSING)
        if seq is MISSING or isinstance(seq, bool) or not isinstance(seq, (int, str)):
            bad("Each allocation requires a compartment_seq")
        tons = req_num(entry, "tons", gt=Decimal("0")).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP)
        cargo_class = req_enum(entry, "cargo_class", ("STANDARD", "MEDICATED"))
        parsed.append({"compartment_seq": seq, "tons": tons, "cargo_class": cargo_class})
    return parsed


@bp.post("/api/trips")
def create_trip():
    uid, role = authenticate()
    data = get_body()
    truck_id = req_str(data, "truck_id")
    order_id = req_str(data, "order_id")
    departure = req_dt(data, "planned_departure_at")
    ret = req_dt(data, "planned_return_at")
    if ret <= departure:
        bad("planned_return_at must be strictly after planned_departure_at")
    allocations = parse_allocations(data)
    authorize(role, uid, {"MillManager"})
    truck = STORE["trucks"].get(truck_id)
    if truck is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Truck {truck_id} not found")
    order = STORE["orders"].get(order_id)
    if order is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Order {order_id} not found")
    # Layer 6 (state)
    if truck["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Truck is not AVAILABLE")
    if order["status"] not in ("IN_PRODUCTION", "COMPLETED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order must be IN_PRODUCTION or COMPLETED to schedule a trip")
    if order_blocked(order_id):
        raise ApiError("ERR_ORDER_BLOCKED", 409, "Order has a batch in HOLD")
    # Layer 7 (safety), listed order: cargo-class consistency, then capability
    expected_class = "MEDICATED" if order["is_medicated"] else "STANDARD"
    for a in allocations:
        if a["cargo_class"] != expected_class:
            raise ApiError("ERR_CARGO_CLASS_MIX", 422,
                           "Allocation cargo_class disagrees with the order's medicated flag")
    if order["is_medicated"] and truck["cargo_class_capability"] != "MEDICATED_CAPABLE":
        raise ApiError("ERR_TRUCK_NOT_MEDICATED_CAPABLE", 422,
                       "Medicated cargo requires a MEDICATED_CAPABLE truck")
    # Layer 8 (temporal): pure half-open truck window, back-to-back allowed
    if truck_window_conflict(truck_id, departure, ret):
        raise ApiError("ERR_TRUCK_WINDOW_CONFLICT", 409,
                       "Window collides with another non-terminal trip of the truck")
    # Layer 9 (constraint): compartment capacity BEFORE order tonnage over-allocation
    compartments = {c["compartment_seq"]: c for c in truck["compartments"]}
    total = Decimal("0")
    for a in allocations:
        comp = compartments.get(a["compartment_seq"])
        if comp is None:
            bad(f"Truck has no compartment_seq {a['compartment_seq']!r}")
        if a["tons"] > comp["capacity_tons"]:
            raise ApiError("ERR_COMPARTMENT_CAPACITY_EXCEEDED", 422,
                           "Allocation exceeds the compartment's capacity_tons")
        total += a["tons"]
    allocated = sum((t["total_tons"] for t in STORE["trips"].values()
                     if t["order_id"] == order_id and t["status"] != "CANCELLED"),
                    Decimal("0"))
    if allocated + total > order["tons"]:
        raise ApiError("ERR_ORDER_TONNAGE_OVERALLOCATED", 422,
                       "Trips would carry more than the order's tons")
    rec = make_record()
    rec.update(truck_id=truck_id, order_id=order_id, planned_departure_at=departure,
               planned_return_at=ret, compartment_allocations=allocations,
               total_tons=total, status="PLANNED")
    STORE["trips"][rec["id"]] = rec
    return success(ser_trip(rec), 201)


@bp.get("/api/trips")
def list_trips():
    uid, role = authenticate()
    authorize(role, uid, {"MillManager", "Customer"})
    items = sorted_items(STORE["trips"])
    if role == "Customer":
        own = {o["id"] for o in STORE["orders"].values() if o["customer_id"] == uid}
        items = [t for t in items if t["order_id"] in own]
    truck_id = request.args.get("truck_id")
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    if truck_id is not None:
        items = [t for t in items if t["truck_id"] == truck_id]
    if order_id is not None:
        items = [t for t in items if t["order_id"] == order_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items)
    return success([ser_trip(t) for t in page], 200, meta)


@bp.get("/api/trips/<tid>")
def get_trip(tid):
    uid, role = authenticate()
    authorize(role, uid, {"MillManager", "Customer"})
    return success(ser_trip(_get_trip_scoped(tid, role, uid)), 200)


@bp.post("/api/trips/<tid>/load")
def load_trip(tid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    t = _get_trip_scoped(tid, role, uid)
    if t["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PLANNED trip can begin loading")
    order = STORE["orders"][t["order_id"]]
    if order["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be COMPLETED to load")
    if order_blocked(t["order_id"]):
        raise ApiError("ERR_ORDER_BLOCKED", 409, "Order has a batch in HOLD")
    t["status"] = "LOADING"
    bump(t)
    return success(ser_trip(t), 200)


@bp.post("/api/trips/<tid>/depart")
def depart_trip(tid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    t = _get_trip_scoped(tid, role, uid)
    if t["status"] != "LOADING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a LOADING trip can depart")
    t["status"] = "IN_TRANSIT"
    bump(t)
    return success(ser_trip(t), 200)


@bp.post("/api/trips/<tid>/deliver")
def deliver_trip(tid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    t = _get_trip_scoped(tid, role, uid)
    if t["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an IN_TRANSIT trip can be delivered")
    t["status"] = "DELIVERED"
    bump(t)
    maybe_bubble_order_delivered(STORE["orders"][t["order_id"]])
    return success(ser_trip(t), 200)


@bp.post("/api/trips/<tid>/cancel")
def cancel_trip(tid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    t = _get_trip_scoped(tid, role, uid)
    # Manual cancellation is PLANNED-only; LOADING trips cancel solely through
    # the order-blocked cascade (PRD 3.9).
    if t["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PLANNED trip can be cancelled")
    t["status"] = "CANCELLED"
    bump(t)
    return success(ser_trip(t), 200)
