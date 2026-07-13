"""In-memory data store and the logical mission clock (PRD 2.4, 2.5).

The store starts EMPTY on every boot. Nothing is seeded or preloaded; every
entity is created through the API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

from errors import NOT_FOUND, err

CLOCK_EPOCH = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.service_areas = {}
        self.nests = {}
        self.drones = {}
        self.batteries = {}
        self.customers = {}
        self.orders = {}
        self.flights = {}
        self.authorizations = {}
        self.geofence_zones = {}
        self.weather_observations = {}
        self.delivery_drops = {}
        self.incidents = {}
        self.maintenance_logs = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    # --- logical clock -----------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, value):
        self.clock = value

    # --- identity ----------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


db = Store()

_COLLECTIONS = {
    "ServiceArea": "service_areas",
    "Nest": "nests",
    "Drone": "drones",
    "Battery": "batteries",
    "Customer": "customers",
    "Order": "orders",
    "Flight": "flights",
    "AirspaceAuthorization": "authorizations",
    "GeofenceZone": "geofence_zones",
    "WeatherObservation": "weather_observations",
    "DeliveryDrop": "delivery_drops",
    "Incident": "incidents",
    "MaintenanceLog": "maintenance_logs",
}


def collection(entity):
    return getattr(db, _COLLECTIONS[entity])


def get_or_404(entity, ident):
    """Fetch by id or raise the entity's not-found error (PRD 2.6)."""
    if not isinstance(ident, str):
        raise err(NOT_FOUND[entity])
    row = collection(entity).get(ident)
    if row is None:
        raise err(NOT_FOUND[entity])
    return row


def new_record(entity, fields, versioned=True):
    """Create a record with the common audit fields (PRD 2.5)."""
    now = db.now()
    rec = dict(fields)
    rec["id"] = db.new_id()
    rec["created_at"] = now
    rec["_seq"] = db.next_seq()
    rec["_entity"] = entity
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    collection(entity)[rec["id"]] = rec
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at, advance version (PRD 2.5)."""
    rec["updated_at"] = db.now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def sorted_rows(rows):
    """Default ordering: created_at ascending; insertion order breaks ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
