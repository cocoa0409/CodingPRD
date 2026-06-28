"""In-memory data store. Every collection is a dict keyed by entity id.
The store starts EMPTY on every boot — no seeding, no preloaded entities.
All entities are created by tests through the declared API surface."""
import uuid

from clock import iso, clock


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.customers = {}
        self.compliance_screens = {}
        self.fee_schedules = {}
        self.cash_drawers = {}
        self.transactions = {}
        self.check_items = {}
        self.money_orders = {}
        self.wire_transfers = {}
        self.bill_payments = {}
        self.prepaid_card_loads = {}
        self.returned_items = {}


db = Store()

_seq_counter = [0]
_mo_serial_counter = [0]


def _next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


def next_money_order_serial():
    """Server-minted printed serial, unique across all MoneyOrders (PRD §3.6)."""
    _mo_serial_counter[0] += 1
    return "MO%010d" % _mo_serial_counter[0]


def common_fields():
    """created_at/updated_at on the logical clock; version starts at 1
    (PRD §2.4). _seq is an internal monotonic creation counter for stable
    list ordering when logical-clock timestamps coincide; never serialized."""
    now = clock.now()
    return {
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }


def audit_fields():
    """ComplianceScreen is an immutable audit record: id + created_at only,
    no updated_at, no version (PRD §2.4)."""
    return {
        "created_at": clock.now(),
        "_seq": _next_seq(),
    }


def touch(entity):
    """Refresh updated_at on the logical clock and bump version by 1.
    Every mutation — direct or cascade — advances the resource's own
    updated_at and version (PRD §2.4)."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity["version"] + 1


# Datetime fields that need ISO serialization on output.
_DT_FIELDS = {
    "created_at",
    "updated_at",
    "limit_window_opened_at",
}


def serialize(entity):
    """Return a JSON-safe copy: datetime fields -> ISO strings; internal
    underscore-prefixed keys (e.g. _seq, _creating_teller_id) are omitted."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in _DT_FIELDS:
            out[k] = iso(v) if v is not None else None
        else:
            out[k] = v
    return out
