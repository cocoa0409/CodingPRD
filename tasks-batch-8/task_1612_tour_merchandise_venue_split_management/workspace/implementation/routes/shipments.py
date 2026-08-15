"""Shipment endpoints (PRD §3.3)."""

from flask import Blueprint, request

from clock import now, now_iso_ms, parse_iso, now_iso_ms as _ts
from db import DB
from errors import (
    ERR_TOUR_NOT_FOUND,
    ERR_SHOW_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_CROSS_TOUR_REFERENCE,
    ERR_SHIPMENT_NOT_DRAFT,
    ERR_SHIPMENT_NOT_DISPATCHED,
    ERR_ALREADY_TERMINAL,
    ERR_LEAD_TIME_VIOLATION,
    ERR_INSUFFICIENT_STOCK,
    ERR_INSUFFICIENT_ALLOCATION,
    ERR_INVALID_SHOW_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_string,
    require_enum,
    base_fields,
    touch,
    paginate,
    new_id,
    SIZES_SIZED,
)
from response import success_object, success_list
from services import core
from services.core import compute_warehouse_stock, allocation_on_hand, find_allocation, LEAD_TIME
from services.serializers import shipment_view

bp = Blueprint("shipments", __name__)


def get_shipment_or_404(shipment_id):
    s = DB.shipments.get(shipment_id)
    if s is None:
        raise err(ERR_SHIPMENT_NOT_FOUND, 404, "No Shipment with the given id")
    return s


def _validate_lines(lines):
    """Returns normalized [{product_id, size, quantity}]; validates shape, size
    validity per product, and product existence."""
    if not isinstance(lines, list) or len(lines) == 0:
        raise err(ERR_VALIDATION, 400, "lines must be a non-empty list")
    out = []
    for line in lines:
        if not isinstance(line, dict):
            raise err(ERR_VALIDATION, 400, "Each shipment line must be an object")
        pid = line.get("product_id")
        size = line.get("size")
        qty = line.get("quantity")
        if pid is None:
            raise err(ERR_VALIDATION, 400, "Missing required field: product_id")
        product = DB.products.get(pid)
        if product is None:
            raise err(ERR_PRODUCT_NOT_FOUND, 404, "No Product with the given id")
        if product["product_type"] == "BUNDLE":
            raise err(ERR_VALIDATION, 400, "BUNDLE products are not shippable")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise err(ERR_VALIDATION, 400, "line quantity must be a positive integer")
        if product["sized"]:
            if size not in SIZES_SIZED:
                raise err(ERR_VALIDATION, 400,
                          "line size must be one of S, M, L, XL for sized products")
        else:
            if size != "OS":
                raise err(ERR_VALIDATION, 400,
                          "line size must be OS for non-sized products")
        out.append({"product_id": pid, "size": size, "quantity": qty})
    return out


@bp.post("/merch/shipments")
def create_shipment():
    require_role("TourManager")
    body = get_json_body()
    tour_id = body.get("tour_id")
    origin_type = require_enum(body, "origin_type", ("WAREHOUSE", "SHOW"), required=True)
    origin_show_id = body.get("origin_show_id")
    destination_show_id = body.get("destination_show_id")

    if tour_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: tour_id")
    if destination_show_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: destination_show_id")

    tour = DB.tours.get(tour_id)
    if tour is None:
        raise err(ERR_TOUR_NOT_FOUND, 404, "No Tour with the given id")
    dest = DB.shows.get(destination_show_id)
    if dest is None:
        raise err(ERR_SHOW_NOT_FOUND, 404, "No Show with the given id")

    if origin_type == "SHOW":
        if origin_show_id is None:
            raise err(ERR_VALIDATION, 400,
                      "origin_show_id is required when origin_type=SHOW")
        origin = DB.shows.get(origin_show_id)
        if origin is None:
            raise err(ERR_SHOW_NOT_FOUND, 404, "No Show with the given id")
        if origin_show_id == destination_show_id:
            raise err(ERR_VALIDATION, 400,
                      "origin_show_id must differ from destination_show_id")
    else:
        if origin_show_id is not None:
            raise err(ERR_VALIDATION, 400,
                      "origin_show_id must be null when origin_type=WAREHOUSE")
        origin = None

    lines = _validate_lines(body.get("lines"))

    # Cross-tour coherence: both shows and all products belong to shipment.tour_id.
    if dest["tour_id"] != tour_id:
        raise err(ERR_CROSS_TOUR_REFERENCE, 422,
                  "Destination show must belong to the shipment's tour")
    if origin is not None and origin["tour_id"] != tour_id:
        raise err(ERR_CROSS_TOUR_REFERENCE, 422,
                  "Origin show must belong to the shipment's tour")
    for line in lines:
        if DB.products[line["product_id"]]["tour_id"] != tour_id:
            raise err(ERR_CROSS_TOUR_REFERENCE, 422,
                      "Shipment lines must reference products of the shipment's tour")

    shipment = {
        **base_fields(),
        "tour_id": tour_id,
        "origin_type": origin_type,
        "origin_show_id": origin_show_id,
        "destination_show_id": destination_show_id,
        "lines": lines,
        "status": "DRAFT",
        "dispatched_by_user_id": None,
        "dispatched_at": None,
        "received_by_user_id": None,
    }
    DB.shipments[shipment["id"]] = shipment
    return success_object(shipment_view(shipment), status=201)


@bp.get("/merch/shipments")
def list_shipments():
    require_auth()
    tour_id = request.args.get("tour_id")
    destination_show_id = request.args.get("destination_show_id")
    origin_show_id = request.args.get("origin_show_id")
    items = list(DB.shipments.values())
    if tour_id is not None:
        items = [s for s in items if s["tour_id"] == tour_id]
    if destination_show_id is not None:
        items = [s for s in items if s["destination_show_id"] == destination_show_id]
    if origin_show_id is not None:
        items = [s for s in items if s["origin_show_id"] == origin_show_id]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([shipment_view(s) for s in page], limit, offset, total)


@bp.get("/merch/shipments/<shipment_id>")
def get_shipment(shipment_id):
    require_auth()
    return success_object(shipment_view(get_shipment_or_404(shipment_id)))


def _source_available(shipment, line):
    """Available units at the source for one line."""
    if shipment["origin_type"] == "WAREHOUSE":
        return compute_warehouse_stock(line["product_id"]).get(line["size"], 0), "WAREHOUSE"
    alloc = find_allocation(shipment["origin_show_id"], line["product_id"], line["size"])
    if alloc is None:
        return 0, "SHOW"
    return allocation_on_hand(alloc), "SHOW"


def _decrement_source(shipment, sign=-1):
    """sign=-1: decrement on dispatch; sign=+1: restore on cancel-from-DISPATCHED.

    WAREHOUSE-origin stock is derived from shipment status in
    compute_warehouse_stock (DRAFT/CANCELLED excluded), so only SHOW-origin
    allocations need explicit adjustment here.
    """
    if shipment["origin_type"] == "WAREHOUSE":
        return
    for line in shipment["lines"]:
        alloc = find_allocation(shipment["origin_show_id"], line["product_id"], line["size"])
        if alloc is not None:
            alloc["quantity_allocated"] += sign * line["quantity"]
            touch(alloc)


@bp.post("/merch/shipments/<shipment_id>/dispatch")
def dispatch_shipment(shipment_id):
    user_id, role = require_role("TourManager")
    shipment = get_shipment_or_404(shipment_id)
    if shipment["status"] != "DRAFT":
        if shipment["status"] in ("RECEIVED", "CANCELLED"):
            raise err(ERR_ALREADY_TERMINAL, 409,
                      "Shipment is in a terminal state")
        raise err(ERR_SHIPMENT_NOT_DRAFT, 409, "Dispatch requires a DRAFT shipment")

    dest = DB.shows[shipment["destination_show_id"]]
    dispatch_instant = now()
    if parse_iso(dest["show_date"]) < dispatch_instant + LEAD_TIME:
        raise err(ERR_LEAD_TIME_VIOLATION, 409,
                  "Destination show_date must be at least 48 hours after dispatch")

    # Stock sufficiency against the source.
    for line in shipment["lines"]:
        available, kind = _source_available(shipment, line)
        if line["quantity"] > available:
            if kind == "WAREHOUSE":
                raise err(ERR_INSUFFICIENT_STOCK, 409,
                          "Requested quantity exceeds warehouse stock")
            raise err(ERR_INSUFFICIENT_ALLOCATION, 409,
                      "Requested quantity exceeds origin allocation quantity_on_hand")

    _decrement_source(shipment, sign=-1)
    shipment["status"] = "DISPATCHED"
    shipment["dispatched_by_user_id"] = user_id
    shipment["dispatched_at"] = now_iso_ms()
    touch(shipment)
    return success_object(shipment_view(shipment))


@bp.post("/merch/shipments/<shipment_id>/receive")
def receive_shipment(shipment_id):
    user_id, role = require_role("TourManager")
    shipment = get_shipment_or_404(shipment_id)
    if shipment["status"] != "DISPATCHED":
        if shipment["status"] in ("RECEIVED", "CANCELLED"):
            raise err(ERR_ALREADY_TERMINAL, 409,
                      "Shipment is in a terminal state")
        raise err(ERR_SHIPMENT_NOT_DISPATCHED, 409,
                  "Receive requires a DISPATCHED shipment")

    dest = DB.shows[shipment["destination_show_id"]]
    if dest["status"] not in ("SCHEDULED", "OPEN"):
        raise err(ERR_INVALID_SHOW_STATE, 409,
                  "Destination show must be SCHEDULED or OPEN")

    if user_id == shipment["dispatched_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403,
                  "The receiver must differ from the dispatcher")

    for line in shipment["lines"]:
        alloc = find_allocation(shipment["destination_show_id"], line["product_id"], line["size"])
        if alloc is None:
            alloc = {
                "id": new_id(),
                "created_at": _ts(),
                "updated_at": _ts(),
                "version": 1,
                "show_id": shipment["destination_show_id"],
                "product_id": line["product_id"],
                "size": line["size"],
                "quantity_allocated": 0,
                "quantity_returned": 0,
                "quantity_liquidated": 0,
                "quantity_shrunk": 0,
            }
            DB.allocations[alloc["id"]] = alloc
        alloc["quantity_allocated"] += line["quantity"]
        touch(alloc)

    shipment["status"] = "RECEIVED"
    shipment["received_by_user_id"] = user_id
    touch(shipment)
    return success_object(shipment_view(shipment))


@bp.post("/merch/shipments/<shipment_id>/cancel")
def cancel_shipment(shipment_id):
    user_id, role = require_role("TourManager")
    shipment = get_shipment_or_404(shipment_id)
    if shipment["status"] in ("RECEIVED", "CANCELLED"):
        raise err(ERR_ALREADY_TERMINAL, 409,
                  "Shipment is already in a terminal state")
    if shipment["status"] == "DISPATCHED":
        # Compensating restore of the source.
        _decrement_source(shipment, sign=+1)
    shipment["status"] = "CANCELLED"
    touch(shipment)
    return success_object(shipment_view(shipment))
