"""In-memory data store. Each entity table is a dict[id -> entity_dict].

Entities carrying common fields persist `id`, `created_at`, `updated_at`, `version`.
PaymentEvent persists `id` and `created_at` only.
"""
from threading import RLock
from clock import clock
from common import new_id


class Store:
    def __init__(self):
        self.lock = RLock()
        self.cabinets = {}
        self.slots = {}
        self.devices = {}
        self.pricing_plans = {}
        self.users = {}
        self.rentals = {}
        self.repair_tickets = {}
        self.operator_tasks = {}
        self.location_partners = {}
        self.settlements = {}
        self.payment_events = {}
        self.maintenance_windows = {}
        # Index for idempotency_key -> payment_event id
        self.payment_event_keys = {}

    def reset(self):
        with self.lock:
            self.cabinets.clear()
            self.slots.clear()
            self.devices.clear()
            self.pricing_plans.clear()
            self.users.clear()
            self.rentals.clear()
            self.repair_tickets.clear()
            self.operator_tasks.clear()
            self.location_partners.clear()
            self.settlements.clear()
            self.payment_events.clear()
            self.maintenance_windows.clear()
            self.payment_event_keys.clear()


db = Store()


def make_common_fields():
    now = clock.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def bump(entity: dict) -> None:
    """Advance updated_at to clock.now() and increment version by 1."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 1) + 1
