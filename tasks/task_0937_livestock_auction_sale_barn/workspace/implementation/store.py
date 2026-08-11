"""In-memory store. Plain dicts keyed by id. Nothing is seeded, ever.

Every entity a caller needs is created by the caller through the declared
endpoints; the store starts empty on every boot and a start.sh re-invocation
wipes every byte of state.

ID DETERMINISM: ids are valid UUID-shaped strings whose high 32 bits are a
monotonic creation counter, so ascending `id` == creation order. Any PRD
ordering rule that tie-breaks on insertion order is therefore deterministic
across runs. This is an id-minting policy, NOT seeded data.
"""
import itertools
import uuid

from clock import clock, render_instant

TABLES = [
    "parties", "sale_days", "pens", "scales", "drover_crews", "consignments",
    "lots", "weigh_tickets", "pen_moves", "buyer_registrations", "bids",
    "purchases", "buyer_invoices", "settlements", "charge_lines",
    "inspection_records", "load_manifests", "load_lines",
]

db = {name: {} for name in TABLES}

_counter = itertools.count(1)


def new_id():
    n = next(_counter)
    rest = uuid.uuid4().hex[8:]
    h = "%08x" % (n & 0xFFFFFFFF) + rest
    return "%s-%s-%s-%s-%s" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])


def reset():
    for name in TABLES:
        db[name].clear()
    clock.reset()


def insert(table, row):
    row["id"] = row.get("id") or new_id()
    row["_seq"] = int(row["id"][:8], 16)
    stamp = render_instant(clock.now())
    row.setdefault("created_at", stamp)
    row["_created_dt"] = clock.now()
    db[table][row["id"]] = row
    return row


def insert_versioned(table, row):
    """Insert a row that carries updated_at + version (PRD 2.4)."""
    row = insert(table, row)
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    return row


def touch(row):
    """Mutation bookkeeping: refresh updated_at, increment version."""
    if "version" in row:
        row["updated_at"] = render_instant(clock.now())
        row["version"] = row["version"] + 1
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return db[table].get(row_id)


def all_rows(table):
    """Every row of a table in creation order."""
    return sorted(db[table].values(), key=lambda r: r["_seq"])


def find(table, **criteria):
    out = []
    for row in all_rows(table):
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return out
