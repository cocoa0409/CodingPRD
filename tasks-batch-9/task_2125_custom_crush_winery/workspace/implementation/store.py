"""In-memory store, logical clock and timestamp helpers.

Every byte of state lives in this process. Nothing is persisted; a fresh
process starts with a completely empty building and a logical clock reading
exactly 2026-08-01T00:00:00Z.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# The logical clock's value before it is ever repositioned.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Database:
    def __init__(self):
        self.clients = {}
        self.contracts = {}
        self.vessels = {}
        self.allocations = {}
        self.intakes = {}
        self.lots = {}
        self.trials = {}
        self.work_orders = {}
        self.lines = {}
        self.runs = {}
        self.dry_goods = {}
        self.reports = {}
        self.release_orders = {}
        # Book of loss events, used by the TTB reconciliation loss line.
        # Each entry: {"client_id": str, "at": datetime, "gallons": Decimal}
        self.loss_events = []
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Database()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant. Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    return iso(db.clock)


def whole_days(start, end):
    """Whole 86400-second days between two instants, floored, never negative."""
    if start is None or end is None:
        return 0
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 86400)


def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to a whole cent, returning an int."""
    return int(rhu(value, 0))


def new_entity(extra=None):
    stamp = now_iso()
    ent = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    ent["_seq"] = db.next_seq()
    ent["_created_dt"] = db.now()
    if extra:
        ent.update(extra)
    return ent


def touch(ent):
    """Full mutation: refresh updated_at and advance version by exactly 1."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent["version"] + 1
    return ent


def sort_key(ent):
    """Default list ordering: created_at ascending, stable by creation order."""
    return (ent.get("_created_dt") or CLOCK_EPOCH, ent.get("_seq", 0))


def public(ent):
    """Strip internal (underscore-prefixed) bookkeeping fields."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
