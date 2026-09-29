"""In-memory data store, logical clock and mutation bookkeeping.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded. All state is created by clients through the declared
endpoints.
"""

import copy
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from constants import DEFAULT_LOGICAL_CLOCK

UTC = timezone.utc

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:[.,](\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Tolerant ISO-8601 parser. Returns an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def fmt_iso(dt):
    """Canonical ISO-8601 UTC rendering with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return fmt_iso(datetime.now(tz=UTC))


class Store:
    COLLECTIONS = (
        "equipment_models",
        "model_revisions",
        "test_rigs",
        "test_runs",
        "firmware_releases",
        "firmware_certifications",
        "facilities",
        "orders",
        "order_lines",
        "service_partners",
        "install_jobs",
        "serialized_assets",
        "pm_programs",
        "maintenance_visits",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_iso(DEFAULT_LOGICAL_CLOCK)

    # -- logical clock -------------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_iso(self.clock)

    def set_clock(self, dt):
        self.clock = dt

    # -- transactional snapshot ---------------------------------------------
    def snapshot(self):
        return (
            {name: copy.deepcopy(getattr(self, name)) for name in self.COLLECTIONS},
            self.clock,
        )

    def restore(self, snap):
        data, clock = snap
        for name in self.COLLECTIONS:
            setattr(self, name, data[name])
        self.clock = clock


store = Store()


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
_META_FIELDS = ("version", "updated_at")
_active_mutations = set()


def new_id():
    return str(uuid.uuid4())


def new_entity(fields):
    stamp = store.now_iso()
    row = {"id": new_id(), "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    return row


def _payload(entity):
    return {k: v for k, v in entity.items() if k not in _META_FIELDS}


@contextmanager
def mutate(entity):
    """Bump version/updated_at once iff a stored field actually changed.

    Re-entrant: nested mutations of the same row collapse into one bump.
    """
    key = id(entity)
    if key in _active_mutations:
        yield entity
        return
    _active_mutations.add(key)
    before = copy.deepcopy(_payload(entity))
    try:
        yield entity
    finally:
        _active_mutations.discard(key)
    if _payload(entity) != before:
        entity["version"] += 1
        entity["updated_at"] = store.now_iso()


def bump(entity):
    """Unconditional version bump (used where the PRD mandates +1)."""
    entity["version"] += 1
    entity["updated_at"] = store.now_iso()


@contextmanager
def mutate_forced(entity):
    """Like mutate() but always bumps exactly once.

    Used for the three version-pinned writes of PRD 2.7, where the parent's
    version is incremented by one on success regardless of value changes.
    Nested mutate() calls on the same row are absorbed.
    """
    key = id(entity)
    reentrant = key in _active_mutations
    _active_mutations.add(key)
    try:
        yield entity
    finally:
        if not reentrant:
            _active_mutations.discard(key)
    if not reentrant:
        bump(entity)


def clear_mutation_state():
    _active_mutations.clear()
