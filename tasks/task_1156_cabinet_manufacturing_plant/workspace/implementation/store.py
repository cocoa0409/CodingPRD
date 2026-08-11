"""In-memory data store + logical clock (PRD §2.6).

The store starts empty on every boot — no seeding. All entities are created
through the declared API surface by the tests.
"""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.dealers = {}
        self.door_styles = {}
        self.finish_specs = {}
        self.components = {}
        self.orders = {}
        self.order_lines = {}
        self.mods = {}
        self.batches = {}
        self.stations = {}
        self.runs = {}
        self.parts = {}
        self.assembly_lines = {}
        self.sub_lots = {}
        self.claims = {}
        self.routes = {}
        self.holds = {}
        # Logical clock: sole source of "now". Startup default per PRD §2.6.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Monotonic creation counter — tiebreak for entities sharing a
        # created_at instant (the logical clock only moves when set).
        self.seq = itertools.count(1)


db = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return db.clock


def stamp(rec: dict) -> None:
    """Initialize common fields at creation (PRD §2.4)."""
    rec["created_at"] = db.clock
    rec["updated_at"] = db.clock
    rec["version"] = 1
    rec["_seq"] = next(db.seq)


def stamp_part(rec: dict) -> None:
    """Parts are immutable: id + created_at only (PRD §2.4)."""
    rec["created_at"] = db.clock
    rec["_seq"] = next(db.seq)


def touch(rec: dict) -> None:
    """Mutation: version increments by exactly 1 and updated_at refreshes."""
    rec["version"] += 1
    rec["updated_at"] = db.clock
