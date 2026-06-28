"""In-memory data store. Starts empty on every boot — NO seeding.

Each collection is a dict keyed by the resource's UUID id. A monotonic
sequence counter preserves creation order for deterministic ascending sort.
"""
import uuid

from clock import clock


class Store:
    def __init__(self):
        # ten primary resources (carry id/created_at/updated_at/version)
        self.accounts = {}
        self.water_tests = {}
        self.systems = {}
        self.rental_contracts = {}
        self.routes = {}
        self.route_stops = {}
        self.cartridge_schedules = {}
        self.service_visits = {}
        self.warranty_claims = {}
        self.invoices = {}
        # two lightweight reference entities (id + created_at only)
        self.customers = {}
        self.field_techs = {}
        # uniqueness index for Customer.email
        self.customer_emails = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_primary(fields):
    """Build a primary resource dict with system-managed common fields.

    PRD §2.4: id (UUID, no prefix), created_at, updated_at (ISO8601 .SSSZ),
    version (integer starting at 1, +1 on each mutation).
    """
    now = clock.iso()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec.update(fields)
    rec["_seq"] = db.next_seq()
    return rec


def new_reference(fields):
    """Customer / FieldTech: id + created_at only (PRD §2.4)."""
    rec = {
        "id": new_id(),
        "created_at": clock.iso(),
    }
    rec.update(fields)
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Mutation bookkeeping: refresh updated_at, bump version (PRD §2.4, §2.7)."""
    rec["updated_at"] = clock.iso()
    rec["version"] = rec["version"] + 1
