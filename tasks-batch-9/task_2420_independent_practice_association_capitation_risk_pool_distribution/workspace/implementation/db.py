"""In-memory store, logical clock and datetime plumbing.

Storage is process-local and starts completely EMPTY on every boot: the
benchmark harness restarts this server before each test and every entity is
built by the tests through the declared endpoints.  Nothing is seeded here.
"""

import datetime
import re
import uuid

from flask import g

UTC = datetime.timezone.utc

# PRD 2.5 — before the clock has been set it reads exactly this instant.  The
# server must never fall back to the host machine's wall clock for it.
LOGICAL_CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_instant_seconds(dt):
    """ISO 8601 UTC at whole-second precision (no fractional digits)."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


class Instant:
    """A datetime plus the literal text it arrived as.

    Values supplied by a caller (or by the logical clock, which a caller sets)
    are echoed back exactly as given so a round trip is lossless; values the
    server computes are rendered in the normalised three-fractional-digit form.
    """

    __slots__ = ("dt", "raw")

    def __init__(self, dt, raw=None):
        self.dt = dt
        self.raw = raw

    def render(self):
        return self.raw if self.raw is not None else fmt_instant(self.dt)

    def __eq__(self, other):
        if not isinstance(other, Instant):
            return NotImplemented
        return self.dt == other.dt and self.render() == other.render()

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return True
        return not result

    def __hash__(self):
        return hash((self.dt, self.render()))

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Instant(%s)" % self.render()


_FRACTION_RE = re.compile(r"\.(\d+)")


def parse_instant(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    # normalise odd fractional-second widths that fromisoformat may reject
    match = _FRACTION_RE.search(candidate)
    if match and len(match.group(1)) not in (3, 6):
        digits = (match.group(1) + "000000")[:6]
        candidate = candidate[: match.start()] + "." + digits + candidate[match.end():]
    try:
        dt = datetime.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return Instant(dt.astimezone(UTC), raw=value)


def add_days(instant, days):
    """Advance an instant by whole days, keeping the source instant's precision.

    A window derived from a caller-supplied instant (an exit notice stamped
    from the logical clock, a pool year end) is rendered at the same precision
    the source instant carried, so `2026-12-31T23:59:59Z` plus 180 days reads
    `2027-06-29T23:59:59Z` rather than gaining a fractional part the source
    never had.
    """
    moved = instant.dt + datetime.timedelta(days=int(days))
    if isinstance(instant.raw, str) and "." not in instant.raw:
        return Instant(moved, raw=fmt_instant_seconds(moved))
    return Instant(moved)


def real_now():
    return Instant(datetime.datetime.now(tz=UTC))


# ---------------------------------------------------------------------------
# stores — all empty at import time and never seeded
# ---------------------------------------------------------------------------
agreements = {}
physicians = {}
enrollees = {}
assignments = {}
files = {}
rows = {}
remittances = {}
pools = {}
claims = {}
recoveries = {}
scorecards = {}
distributions = {}

_state = {"seq": 0, "clock": Instant(LOGICAL_CLOCK_DEFAULT)}


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def clock():
    return _state["clock"]


def set_clock(instant):
    _state["clock"] = instant


def new_id():
    return str(uuid.uuid4())


def audit_stamp():
    """The instant audit fields are stamped with.

    PRD 2.5 forbids substituting the host machine's current time, so audit
    stamps read the logical clock; PRD 2.4 pins their rendering at three
    fractional digits, so the normalised form is used rather than the literal
    text the clock was set with.
    """
    return Instant(clock().dt)


def create(store, versioned=True, **fields):
    entity = {"id": new_id(), "_seq": next_seq()}
    stamp = audit_stamp()
    entity["created_at"] = stamp
    if versioned:
        entity["updated_at"] = stamp
        entity["version"] = 1
    entity.update(fields)
    store[entity["id"]] = entity
    return entity


def touch(entity):
    """Bump version/updated_at at most once per resource per request."""
    marked = getattr(g, "touched_entities", None)
    if marked is None:
        marked = set()
        g.touched_entities = marked
    key = entity["id"]
    if key in marked:
        return
    marked.add(key)
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = audit_stamp()


def apply_fields(entity, **fields):
    """Assign fields, reporting whether anything actually changed."""
    changed = False
    for key, value in fields.items():
        if entity.get(key) != value:
            entity[key] = value
            changed = True
    return changed


def ordered(items):
    """Default list ordering: created_at ascending (stable insertion order)."""
    return sorted(items, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# reverse-reachability helpers
# ---------------------------------------------------------------------------
def physicians_of_agreement(agreement_id):
    return ordered([p for p in physicians.values() if p["agreement_id"] == agreement_id])


def enrollees_of_agreement(agreement_id):
    return ordered([e for e in enrollees.values() if e["agreement_id"] == agreement_id])


def assignments_of_enrollee(enrollee_id):
    return ordered([a for a in assignments.values() if a["enrollee_id"] == enrollee_id])


def assignments_of_physician(physician_id):
    return ordered([a for a in assignments.values() if a["physician_id"] == physician_id])


def rows_of_file(file_id):
    return ordered([r for r in rows.values() if r["file_id"] == file_id])


def remittances_of_file(file_id):
    return ordered([r for r in remittances.values() if r["file_id"] == file_id])


def files_of_agreement(agreement_id):
    return ordered([f for f in files.values() if f["agreement_id"] == agreement_id])


def pools_of_agreement(agreement_id):
    return ordered([p for p in pools.values() if p["agreement_id"] == agreement_id])


def claims_of_pool(pool_id):
    return ordered([c for c in claims.values() if c["pool_id"] == pool_id])


def recoveries_of_pool(pool_id):
    return ordered([r for r in recoveries.values() if r["pool_id"] == pool_id])


def scorecards_of_physician(physician_id):
    return ordered([s for s in scorecards.values() if s["physician_id"] == physician_id])


def distributions_of_pool(pool_id):
    return ordered([d for d in distributions.values() if d["pool_id"] == pool_id])


# ---------------------------------------------------------------------------
# agreement resolution (used by PayerRepresentative ownership checks)
# ---------------------------------------------------------------------------
def agreement_of_physician(physician):
    return agreements.get(physician["agreement_id"])


def agreement_of_enrollee(enrollee):
    return agreements.get(enrollee["agreement_id"])


def agreement_of_assignment(assignment):
    enrollee = enrollees.get(assignment["enrollee_id"])
    if enrollee is not None:
        return agreements.get(enrollee["agreement_id"])
    physician = physicians.get(assignment["physician_id"])
    if physician is not None:
        return agreements.get(physician["agreement_id"])
    return None


def agreement_of_file(enrollment_file):
    return agreements.get(enrollment_file["agreement_id"])


def agreement_of_remittance(remittance):
    enrollment_file = files.get(remittance["file_id"])
    return agreement_of_file(enrollment_file) if enrollment_file else None


def agreement_of_pool(pool):
    return agreements.get(pool["agreement_id"])


def agreement_of_claim(claim):
    return agreements.get(claim["agreement_id"])


def agreement_of_recovery(recovery):
    pool = pools.get(recovery["pool_id"])
    return agreement_of_pool(pool) if pool else None


def agreement_of_scorecard(scorecard):
    physician = physicians.get(scorecard["physician_id"])
    return agreement_of_physician(physician) if physician else None


def agreement_of_distribution(distribution):
    pool = pools.get(distribution["pool_id"])
    return agreement_of_pool(pool) if pool else None
