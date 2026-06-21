"""Shared reservation-related side effects."""
import db
import util
from services import fleet


def release_held_vehicle(reservation_id):
    """Cascade: if a vehicle is RESERVED for this reservation, release it back to
    AVAILABLE (clear held_by, reconcile available_count upward). Used by cancel,
    no-show. Returns the released vehicle or None.
    """
    for v in db.vehicles.values():
        if v["status"] == "RESERVED" and v["held_by_reservation_id"] == reservation_id:
            v["status"] = "AVAILABLE"
            v["held_by_reservation_id"] = None
            util.touch(v)
            fleet.reconcile_class(db.vehicle_classes[v["class_id"]])
            return v
    return None
