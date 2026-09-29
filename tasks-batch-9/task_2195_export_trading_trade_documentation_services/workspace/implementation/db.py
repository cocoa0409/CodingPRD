"""In-memory store. Starts empty on every boot; nothing is ever seeded."""
from decimal import Decimal

from core import ApiError, fmt_dt, new_id, parse_dt

DEFAULT_CLOCK_TEXT = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "buyers", "orders", "shipment_lines", "lcs", "reviews", "findings",
    "documents", "screenings", "licenses", "sailings", "bookings",
    "presentations", "links", "policies", "disputes",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_dt(DEFAULT_CLOCK_TEXT)
        self._counter = 0

    def next_seq(self):
        self._counter += 1
        return self._counter


store = Store()


def now():
    return store.clock


def insert(collection, row, with_version=True):
    seq = store.next_seq()
    row["id"] = row.get("id") or new_id()
    stamp = fmt_dt(store.clock)
    row["created_at"] = stamp
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = seq
    collection[row["id"]] = row
    return row


def touch(row):
    """Register a mutation: refresh updated_at and bump version by one."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = fmt_dt(store.clock)
    return row


def ordered(collection):
    """Rows in ascending created_at order (insertion order breaks ties)."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def serialize_all(rows):
    return [serialize(r) for r in rows]


def require(collection, row_id, error_id, http_status=404):
    if not isinstance(row_id, str) or row_id not in collection:
        raise ApiError(error_id, http_status, "%s: %s" % (error_id, row_id))
    return collection[row_id]
