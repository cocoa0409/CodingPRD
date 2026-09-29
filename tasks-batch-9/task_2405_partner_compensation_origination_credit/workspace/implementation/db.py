"""In-memory data store for the partner compensation service.

The store starts completely empty on every boot. Nothing is seeded, preloaded
or hardcoded here.
"""
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import g

getcontext().prec = 60

D = Decimal

# The logical clock's startup value (PRD 2.5).
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def rhu(value, places=0):
    """Round half up (away from zero) to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


class Store(object):
    def __init__(self):
        self.cycles = {}
        self.partners = {}
        self.matters = {}
        self.allocations = {}
        self.records = {}
        self.claims = {}
        self.assessments = {}
        self.reviews = {}
        self.ballots = {}
        self.awards = {}
        self.payments = {}
        self.transitions = {}
        self._seq = 0
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(store.clock)


def clock_date():
    return store.clock.astimezone(timezone.utc).date()


def parse_date(text):
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def _bumped():
    if not hasattr(g, "bumped"):
        g.bumped = set()
    return g.bumped


def touch(entity):
    """Register a mutation: bump version + updated_at at most once per request."""
    if "version" not in entity:
        return
    marks = _bumped()
    if entity["id"] in marks:
        return
    marks.add(entity["id"])
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def new_entity(fields, common=True):
    e = {"id": new_id()}
    e.update(fields)
    e["created_at"] = now_iso()
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
        # A freshly created row is at version 1 for this request even if the
        # recompute pass immediately derives values for it.
        _bumped().add(e["id"])
    e["_seq"] = store.next_seq()
    return e


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = float(v) if isinstance(v, Decimal) else v
    return out


def apply_changes(entity, new_values):
    """Assign derived values, bumping version/updated_at when something moved."""
    changed = False
    for k, v in new_values.items():
        old = entity.get(k)
        if old is None and v is None:
            continue
        if old is None or v is None or old != v:
            entity[k] = v
            changed = True
    if changed:
        touch(entity)
    return changed
