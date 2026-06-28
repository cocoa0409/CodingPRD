"""In-memory data store. Starts empty on every boot; nothing is ever seeded."""
import itertools
import uuid

from clock import clock, format_iso8601_ms


class DB:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.vendors = {}
        self.factors = {}
        self.solicitations = {}
        self.proposals = {}
        self.factor_scores = {}
        self.awards = {}
        self.contracts = {}
        self.clins = {}
        self.invoices = {}
        self.modifications = {}
        self.protests = {}
        self.cpars = {}
        # Monotonic counter to make creation order (and thus default sort) stable
        # even when several entities share the same logical-clock timestamp.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return format_iso8601_ms(clock.now())


def stamp_create(entity, with_version=True):
    """Apply system-managed fields on create."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    entity["_seq"] = db.next_seq()
    if with_version:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


def touch(entity):
    """Bump version and refresh updated_at on a mutation."""
    entity["version"] = entity.get("version", 0) + 1
    entity["updated_at"] = now_iso()
