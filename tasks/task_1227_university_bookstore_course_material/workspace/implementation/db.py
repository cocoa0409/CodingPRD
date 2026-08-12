"""In-memory store + logical clock. No persistence, no seeding.

The store starts empty on every boot; all entities are created exclusively
through the declared API surface.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # entity collections keyed by id (dicts preserve insertion order,
        # which we rely on as the tiebreak for created_at-equal sorting)
        self.terms = {}
        self.publishers = {}
        self.agreements = {}
        self.titles = {}
        self.faculty = {}
        self.students = {}
        self.sections = {}
        self.enrollments = {}
        self.adoptions = {}
        self.buy_plans = {}
        self.orders = {}
        self.order_lines = {}
        self.ia_charges = {}
        self.wholesale_quotes = {}
        self.buyback_tickets = {}
        self.commission_statements = {}
        # Server-side logical clock. Defaults to 2026-05-01T00:00:00Z and is
        # only ever moved by POST /bookstore/_clock/set_current_utc. Never
        # falls back to wall-clock time.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def now():
    """Current logical time (aware UTC datetime)."""
    return store.clock


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def new_entity():
    """Common fields (PRD §2.4): id, created_at, updated_at, version."""
    n = now()
    return {"id": new_id(), "created_at": n, "updated_at": n, "version": 1}


def touch(ent):
    """Every mutation refreshes updated_at and increments version by exactly one."""
    ent["updated_at"] = now()
    ent["version"] += 1


def pub(ent):
    """Public serialization: datetimes -> formatted strings; everything else as-is."""
    out = {}
    for k, v in ent.items():
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out
