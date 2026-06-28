"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every boot. No entity is seeded, preloaded, or
hardcoded here or anywhere at startup — every entity is created by the test
suite via the declared API surface (PRD Section 3 / Section 4).
"""
import uuid

from clock import clock


def new_id():
    # PRD 2.4: server-minted id — a UUID with no type prefix.
    return str(uuid.uuid4())


def iso(dt):
    # PRD 2.4 / 2.2: ISO 8601 UTC with three fractional digits.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # Each entity collection is a dict id -> record dict.
        self.locations = {}
        self.levels = {}
        self.skills = {}
        self.instructors = {}
        self.parents = {}
        self.students = {}
        self.class_sessions = {}
        self.enrollments = {}
        self.invoices = {}
        self.makeup_credits = {}
        self.makeup_bookings = {}
        self.assessments = {}


store = Store()

# Monotonic creation counter. Used only as an internal, deterministic tie-break
# for records sharing an identical created_at (the logical clock has millisecond
# precision, so same-instant creations collide). It reflects true creation order
# and is never serialized — and crucially is never the entity id, which the PRD
# forbids as a tie-break for the sibling discount.
_seq_counter = 0


def _next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def common_fields_on_create():
    """PRD 2.4: every persisted resource carries id, created_at, updated_at, version.
    version begins at 1 on creation."""
    now = clock.now()
    ts = iso(now)
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": _next_seq(),
    }


def touch(record):
    """PRD 2.4: version increments by one on every mutation that changes the
    resource; updated_at is refreshed to the current logical instant."""
    record["version"] += 1
    record["updated_at"] = iso(clock.now())
