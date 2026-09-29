"""In-memory data store, logical clock and row helpers.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded here -- every row is created by a caller through the declared API
surface.
"""

import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

# PRD 2.4: the logical clock starts at this instant on a fresh boot.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "distributors",
    "raw_materials",
    "formulations",
    "formulation_components",
    "design_licenses",
    "print_films",
    "product_skus",
    "press_lines",
    "test_panels",
    "test_results",
    "production_runs",
    "batches",
    "allocations",
    "allocation_lines",
    "warranty_claims",
)

NOT_FOUND_ERROR = {
    "distributors": "ERR_DISTRIBUTOR_NOT_FOUND",
    "raw_materials": "ERR_RAW_MATERIAL_NOT_FOUND",
    "formulations": "ERR_FORMULATION_NOT_FOUND",
    "formulation_components": "ERR_FORMULATION_COMPONENT_NOT_FOUND",
    "design_licenses": "ERR_DESIGN_LICENSE_NOT_FOUND",
    "print_films": "ERR_PRINT_FILM_NOT_FOUND",
    "product_skus": "ERR_PRODUCT_SKU_NOT_FOUND",
    "press_lines": "ERR_PRESS_LINE_NOT_FOUND",
    "test_panels": "ERR_TEST_PANEL_NOT_FOUND",
    "production_runs": "ERR_PRODUCTION_RUN_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "allocations": "ERR_ALLOCATION_NOT_FOUND",
    "warranty_claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
}


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0


db = Store()
request_lock = threading.RLock()


def now():
    """The logical clock -- every server-stamped instant reads this."""
    return db.clock


def set_clock(value):
    # Store a plain datetime: every instant the server stamps from the clock
    # takes the PRD 2.4 rendering, never the caller's own text.
    db.clock = datetime(value.year, value.month, value.day, value.hour, value.minute,
                        value.second, value.microsecond, tzinfo=timezone.utc)


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def iso(value):
    d = value.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def new_row(versioned=True):
    stamp = now()
    row = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


_touched = set()


def begin_request():
    _touched.clear()


def touch(row):
    """PRD 2.4/2.9: refresh updated_at and advance version by exactly one.

    A row reached several times while servicing one request advances once.
    """
    if row is None or "version" not in row:
        return row
    if row["id"] in _touched:
        return row
    _touched.add(row["id"])
    row["updated_at"] = now()
    row["version"] = row["version"] + 1
    return row


def sort_key(row):
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=sort_key)


def serialize(row):
    return {k: _ser(v) for k, v in row.items() if not k.startswith("_")}


def _ser(value):
    if isinstance(value, datetime):
        # A client-supplied instant echoes back exactly as it was supplied; only
        # the instants the server stamps take the PRD 2.4 rendering.
        raw = getattr(value, "raw", None)
        return raw if isinstance(raw, str) else iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _ser(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ser(v) for v in value]
    return value
