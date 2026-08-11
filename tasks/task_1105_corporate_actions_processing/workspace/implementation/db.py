"""In-memory data store. The store starts empty on every boot — no seeding."""

TABLES = [
    "securities",
    "accounts",
    "position_lots",
    "event_sources",
    "source_notifications",
    "events",
    "event_amendments",
    "entitlements",
    "elections",
    "bookings",
    "booking_lines",
    "claims",
    "custodian_statements",
    "recon_breaks",
]

store = {name: {} for name in TABLES}


def table(name):
    return store[name]


def insert(name, record):
    store[name][record["id"]] = record
    return record


def get(name, rid):
    return store[name].get(rid)


def all_rows(name):
    """All rows in creation order (creation timestamp ascending, PRD 2.3)."""
    return sorted(store[name].values(), key=lambda r: r["_seq"])


def public(record):
    """Strip internal keys (anything starting with '_') for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
