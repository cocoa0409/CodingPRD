"""Vehicle endpoints + state-machine transitions (PRD §3.1, §3.4, §3.8)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from pagination import paginate
from response import array_response, object_response
from services import fleet
from services.intervals import overlaps

bp = Blueprint("vehicles", __name__)


@bp.route("/vehicles", methods=["POST"])
def create_vehicle():
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    body = request.get_json(silent=True) or {}

    location_id = util.require_str(body, "location_id")
    class_id = util.require_str(body, "class_id")
    plate = util.require_str(body, "plate")
    odometer = util.require_int(body, "odometer_miles", minimum=0)
    fuel = util.optional_int_in_range(body, "fuel_level_eighths", 0, 8, default=8)

    lookup.get_location(location_id)
    vclass = lookup.get_vehicle_class(class_id)

    for existing in db.vehicles.values():
        if existing["plate"] == plate:
            raise err("ERR_INVALID_REQUEST", "Vehicle plate already exists: %s" % plate)

    rec = util.stamp_new(
        {
            "location_id": location_id,
            "class_id": class_id,
            "plate": plate,
            "status": "AVAILABLE",
            "odometer_miles": odometer,
            "fuel_level_eighths": fuel,
            "held_by_reservation_id": None,
        }
    )
    db.vehicles[rec["id"]] = rec
    # Adding a vehicle changes the class's denormalized counts (cascade).
    fleet.reconcile_class(vclass)
    return object_response(serialize.vehicle(rec), 201)


@bp.route("/vehicles", methods=["GET"])
def list_vehicles():
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})

    status = request.args.get("status")
    class_id = request.args.get("class_id")
    location_id = request.args.get("location_id")
    held_by = request.args.get("held_by_reservation_id")

    matches = [
        v
        for v in db.vehicles.values()
        if (status is None or v["status"] == status)
        and (class_id is None or v["class_id"] == class_id)
        and (location_id is None or v["location_id"] == location_id)
        and (held_by is None or v["held_by_reservation_id"] == held_by)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.vehicle(v) for v in page], limit, offset, total, 200
    )


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})
    rec = lookup.get_vehicle(vehicle_id)
    return object_response(serialize.vehicle(rec), 200)


def _active_commitment_reservation(vehicle):
    """Return the reservation that constitutes this vehicle's current active
    commitment: its RESERVED-hold reservation, or its ON_RENT agreement's
    reservation. None if the vehicle has no active commitment.
    """
    if vehicle["status"] == "RESERVED" and vehicle["held_by_reservation_id"]:
        return db.reservations.get(vehicle["held_by_reservation_id"])
    if vehicle["status"] == "ON_RENT":
        for ag in db.agreements.values():
            if ag["vehicle_id"] == vehicle["id"] and ag["status"] == "OPEN":
                return db.reservations.get(ag["reservation_id"])
    return None


@bp.route("/vehicles/<vehicle_id>/hold", methods=["POST"])
def hold_vehicle(vehicle_id):
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    body = request.get_json(silent=True) or {}

    # Existence: vehicle (path), then reservation (body) — left to right.
    vehicle = lookup.get_vehicle(vehicle_id)
    reservation_id = util.require_str(body, "reservation_id")
    expected_version = util.require_int(body, "expected_vehicle_version")
    reservation = lookup.get_reservation(reservation_id)

    # Priority 6: OCC version guard fires first.
    if expected_version != vehicle["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_vehicle_version %s does not match current version %s"
            % (expected_version, vehicle["version"]),
        )

    # Priority 7: class/location match + reservation CONFIRMED.
    if (
        reservation["status"] != "CONFIRMED"
        or reservation["class_id"] != vehicle["class_id"]
        or reservation["pickup_location_id"] != vehicle["location_id"]
    ):
        raise err(
            "ERR_CLASS_MISMATCH",
            "reservation must be CONFIRMED and match the vehicle's class/location",
        )

    # Priority 19: double-booking check (before availability).
    commitment = _active_commitment_reservation(vehicle)
    if commitment is not None and overlaps(commitment, reservation):
        raise err(
            "ERR_VEHICLE_DOUBLE_BOOKED",
            "vehicle's active commitment overlaps the target reservation interval",
        )

    # Priority 20: vehicle must be AVAILABLE.
    if vehicle["status"] != "AVAILABLE":
        raise err("ERR_VEHICLE_NOT_AVAILABLE", "vehicle is not AVAILABLE")

    # Apply hold.
    vehicle["status"] = "RESERVED"
    vehicle["held_by_reservation_id"] = reservation_id
    util.touch(vehicle)  # bumps version by 1
    fleet.reconcile_class(db.vehicle_classes[vehicle["class_id"]])
    return object_response(serialize.vehicle(vehicle), 200)


@bp.route("/vehicles/<vehicle_id>/release", methods=["POST"])
def release_vehicle(vehicle_id):
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    vehicle = lookup.get_vehicle(vehicle_id)

    if vehicle["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "vehicle is not RESERVED")

    vehicle["status"] = "AVAILABLE"
    vehicle["held_by_reservation_id"] = None
    util.touch(vehicle)
    fleet.reconcile_class(db.vehicle_classes[vehicle["class_id"]])
    return object_response(serialize.vehicle(vehicle), 200)


@bp.route("/vehicles/<vehicle_id>/return-to-service", methods=["POST"])
def return_to_service(vehicle_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    vehicle = lookup.get_vehicle(vehicle_id)

    if vehicle["status"] != "MAINTENANCE":
        raise err("ERR_INVALID_STATE", "vehicle is not in MAINTENANCE")

    # No FILED incident may remain on this vehicle's last agreement.
    last_agreement = _last_agreement_for_vehicle(vehicle_id)
    if last_agreement is not None:
        for inc in db.incidents.values():
            if inc["agreement_id"] == last_agreement["id"] and inc["status"] == "FILED":
                raise err(
                    "ERR_OPEN_INCIDENT",
                    "a FILED incident remains on this vehicle's last agreement",
                )

    vehicle["status"] = "AVAILABLE"
    util.touch(vehicle)
    fleet.reconcile_class(db.vehicle_classes[vehicle["class_id"]])
    return object_response(serialize.vehicle(vehicle), 200)


@bp.route("/vehicles/<vehicle_id>/retire", methods=["POST"])
def retire_vehicle(vehicle_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    vehicle = lookup.get_vehicle(vehicle_id)

    if vehicle["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "vehicle is not AVAILABLE")

    vehicle["status"] = "RETIRED"
    util.touch(vehicle)
    fleet.reconcile_class(db.vehicle_classes[vehicle["class_id"]])
    return object_response(serialize.vehicle(vehicle), 200)


def _last_agreement_for_vehicle(vehicle_id):
    """The most recently created agreement referencing this vehicle, if any."""
    candidates = [
        ag for ag in db.agreements.values() if ag["vehicle_id"] == vehicle_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda ag: ag["_seq"])
