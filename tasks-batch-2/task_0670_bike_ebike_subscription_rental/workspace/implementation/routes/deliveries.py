from flask import Blueprint, request

from db import db
from clock import parse_clock_field
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_REQUEST, ERR_DELIVERY_TYPE_MISMATCH,
    ERR_DELIVERY_WINDOW_CONFLICT, ERR_INVALID_STATE,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_enum,
    require_string, parse_pagination, paginate,
)
from services.lookups import get_rental, get_delivery
from services.reconcile import recompute_model_counts
from services.bike_ops import select_available_bike
from services.serialize import delivery_view

deliveries_bp = Blueprint("deliveries", __name__)

DELIVERY_TYPES = {"INITIAL", "SWAP", "PICKUP"}
VIEW_ROLES = {"OpsAdmin", "FieldTech", "Subscriber", "FleetManager"}

# delivery_type -> required rental lifecycle_status (priority 7).
TYPE_REQUIRES = {
    "INITIAL": {"RESERVED"},
    "PICKUP": {"RETURN_REQUESTED"},
    "SWAP": {"DELIVERED", "ACTIVE"},
}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intervals share a single instant iff
    a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


@deliveries_bp.route("/deliveries", methods=["POST"])
def create_delivery():
    require_role({"OpsAdmin", "FieldTech"})
    body = get_json_body()
    require_fields(body, ["rental_id", "delivery_type", "address",
                          "window_start_clock", "window_end_clock"])
    with db.lock:
        rental = get_rental(body["rental_id"])
        require_enum(body["delivery_type"], DELIVERY_TYPES, "delivery_type")
        require_string(body["address"], "address")
        try:
            window_start = parse_clock_field(body["window_start_clock"])
            window_end = parse_clock_field(body["window_end_clock"])
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "Delivery window must be ISO-8601 instants.")

        # Priority 7: delivery_type must match rental lifecycle_status.
        if rental["lifecycle_status"] not in TYPE_REQUIRES[body["delivery_type"]]:
            raise err(ERR_DELIVERY_TYPE_MISMATCH,
                      "delivery_type incompatible with rental lifecycle_status.")

        # Priority 8: window must be well-formed (start < end) and not overlap an
        # existing SCHEDULED delivery for the SAME rental.
        if not (window_start < window_end):
            raise err(ERR_DELIVERY_WINDOW_CONFLICT,
                      "window_start_clock must be strictly before window_end_clock.")
        for d in db.deliveries.values():
            if d["rental_id"] == rental["id"] and d["status"] == "SCHEDULED":
                ds = parse_clock_field(d["window_start_clock"])
                de = parse_clock_field(d["window_end_clock"])
                if _intervals_overlap(window_start, window_end, ds, de):
                    raise err(ERR_DELIVERY_WINDOW_CONFLICT,
                              "Delivery window overlaps an existing SCHEDULED delivery.")

        swap_to_bike_id = None
        if body["delivery_type"] == "SWAP":
            replacement = select_available_bike(rental["model_id"], db.bikes)
            if replacement is not None:
                swap_to_bike_id = replacement["id"]

        rec = {
            "rental_id": rental["id"],
            "delivery_type": body["delivery_type"],
            "address": body["address"],
            "window_start_clock": body["window_start_clock"],
            "window_end_clock": body["window_end_clock"],
            "swap_to_bike_id": swap_to_bike_id,
            "status": "SCHEDULED",
        }
        stamp_create(rec)
        db.deliveries[rec["id"]] = rec
    return object_response(delivery_view(rec), 201)


@deliveries_bp.route("/deliveries/<delivery_id>", methods=["GET"])
def fetch_delivery(delivery_id):
    require_role(VIEW_ROLES)
    delivery = get_delivery(delivery_id)
    return object_response(delivery_view(delivery), 200)


@deliveries_bp.route("/deliveries", methods=["GET"])
def list_deliveries():
    require_role(VIEW_ROLES)
    limit, offset = parse_pagination()
    records = list(db.deliveries.values())
    for field in ("rental_id", "swap_to_bike_id", "status"):
        val = request.args.get(field)
        if val:
            records = [r for r in records if r.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response([delivery_view(r) for r in page], limit, offset, total)


@deliveries_bp.route("/deliveries/<delivery_id>/complete", methods=["POST"])
def complete_delivery(delivery_id):
    require_role({"FieldTech"})
    with db.lock:
        delivery = get_delivery(delivery_id)
        if delivery["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Delivery must be SCHEDULED to complete.")
        rental = db.rentals.get(delivery["rental_id"])

        if delivery["delivery_type"] == "INITIAL":
            # Requires rental RESERVED, this INITIAL SCHEDULED, bike RESERVED.
            if rental is None or rental["lifecycle_status"] != "RESERVED":
                raise err(ERR_INVALID_STATE, "Rental must be RESERVED for INITIAL completion.")
            bike = db.bikes.get(rental["bike_id"])
            if bike is None or bike["bike_status"] != "RESERVED":
                raise err(ERR_INVALID_STATE, "Bike must be RESERVED for INITIAL completion.")
            delivery["status"] = "COMPLETED"
            touch(delivery)
            bike["bike_status"] = "OUT"
            touch(bike)
            rental["lifecycle_status"] = "DELIVERED"
            touch(rental)

        elif delivery["delivery_type"] == "SWAP":
            delivery["status"] = "COMPLETED"
            touch(delivery)
            old_bike = db.bikes.get(rental["bike_id"]) if rental else None
            new_bike = db.bikes.get(delivery["swap_to_bike_id"]) if delivery["swap_to_bike_id"] else None
            if old_bike is not None:
                old_bike["bike_status"] = "AVAILABLE"
                old_bike["current_rental_id"] = None
                touch(old_bike)
            if new_bike is not None:
                new_bike["bike_status"] = "OUT"
                new_bike["current_rental_id"] = rental["id"] if rental else None
                touch(new_bike)
                if rental is not None:
                    rental["bike_id"] = new_bike["id"]
                    touch(rental)
            if rental is not None:
                recompute_model_counts(rental["model_id"])

        else:  # PICKUP — collection; no bike/rental side-effect beyond completion.
            delivery["status"] = "COMPLETED"
            touch(delivery)

    return object_response(delivery_view(delivery), 200)
