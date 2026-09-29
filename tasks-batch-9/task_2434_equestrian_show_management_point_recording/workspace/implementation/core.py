"""In-memory store, logical clock, common-field bookkeeping and constants.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded.  Every row is created by an API caller.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from flask import g

from errors import ApiError

# --------------------------------------------------------------------------
# constants (PRD section 3, scaffold calculations)
# --------------------------------------------------------------------------
ROLES = (
    "ShowSecretary",
    "FederationOfficer",
    "RingMaster",
    "Judge",
    "Steward",
    "Exhibitor",
    "GroundsManager",
)
ALL_ROLES = ROLES

COMPETITION_LEVELS = ("LOCAL", "REGIONAL", "NATIONAL", "PREMIER")
SURFACE_TYPES = ("SAND_FIBER", "GRASS", "CLAY")
DISCIPLINES = ("HUNTER", "JUMPER", "EQUITATION", "DRESSAGE")
AGE_GROUPS = ("JUNIOR", "AMATEUR", "OPEN", "PONY")
OFFICIAL_ROLES = ("JUDGE", "STEWARD", "TECHNICAL_DELEGATE")
COVERAGE_TYPES = ("VETERINARIAN", "FARRIER")
CASE_TYPES = ("DRUG_TEST", "WELFARE_CITATION")
FINDINGS = ("NEGATIVE", "POSITIVE", "WARNING")
STANDINGS_BODIES = ("NATIONAL", "REGIONAL")
ACK_OUTCOMES = ("ACCEPTED", "REJECTED")
LICENSE_DECISIONS = ("APPROVE", "RETURN", "DENY")

MAX_LICENSE_REVISIONS = 2
MIN_FOOTING_SCORE = 60
WARMUP_LEAD_MINUTES = 30
COGGINS_VALIDITY_DAYS = 365
MIN_ENTRIES_FOR_POINTS = 3
WELFARE_STRIKE_LIMIT = 2
COVERAGE_CHECKIN_LEAD_MINUTES = 60
OFFICIAL_TRAVEL_GAP_MINUTES = 20
MAX_OFFICIAL_DAILY_MINUTES = 480
REGIONAL_PLACING_CAP = 3
REGIONAL_SHOW_CAP = 20

HEIGHT_FACTOR_BASE_CM = 100
HEIGHT_FACTOR_DIVISOR = 200
JUMPOFF_RATE = Decimal("0.30")
JUMPOFF_CAP = 8
COURSE_WALK_MIN_MINUTES = 10

OFFICE_FEE_WAIVER_CENTS = 100000
OFFICE_FEE_REDUCED_CENTS = 50000
OFFICE_FEE_REDUCED_AMOUNT_CENTS = 2500
OFFICE_FEE_FULL_AMOUNT_CENTS = 5000

BASE_ROUND_SECONDS = {"HUNTER": 90, "JUMPER": 75, "EQUITATION": 100, "DRESSAGE": 300}
PLACE_SHARE_BP = {1: 4000, 2: 2500, 3: 1600, 4: 1100, 5: 800}
NATIONAL_POINTS = {1: 10, 2: 6, 3: 4, 4: 3, 5: 2}
REGIONAL_POINTS = {1: 8, 2: 5, 3: 3}

MIN_OFFICIAL_LICENSE_LEVEL = {"LOCAL": 1, "REGIONAL": 2, "NATIONAL": 3, "PREMIER": 4}
REQUIRED_OFFICIALS = {
    "LOCAL": {"JUDGE": 1, "STEWARD": 1, "TECHNICAL_DELEGATE": 0},
    "REGIONAL": {"JUDGE": 2, "STEWARD": 1, "TECHNICAL_DELEGATE": 0},
    "NATIONAL": {"JUDGE": 2, "STEWARD": 1, "TECHNICAL_DELEGATE": 1},
    "PREMIER": {"JUDGE": 3, "STEWARD": 2, "TECHNICAL_DELEGATE": 1},
}

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq = itertools.count(1)
LOCK = threading.RLock()


class Store(object):
    """Plain in-memory store: one dict per resource type, keyed by id."""

    def __init__(self):
        self.shows = {}
        self.rings = {}
        self.divisions = {}
        self.classes = {}
        self.slots = {}
        self.officials = {}
        self.assignments = {}
        self.riders = {}
        self.horses = {}
        self.entries = {}
        self.class_entries = {}
        self.submissions = {}
        self.cases = {}
        self.coverage_shifts = {}
        self.current_utc = DEFAULT_CLOCK


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def now_clock():
    """The logical clock (never the host wall clock)."""
    return db.current_utc


def iso_ms(dt=None):
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 instant; raise ERR_INVALID_REQUEST when unparseable."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Datetime value must be an ISO 8601 string.")
    text = value.strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Datetime value must be an ISO 8601 string.")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Datetime value is not a parseable ISO 8601 instant.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def minutes_between(start, end):
    return int((end - start).total_seconds() // 60)


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to a whole number, halves away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def bp_share(amount_cents, share_bp):
    return round_half_up(Decimal(int(amount_cents)) * Decimal(int(share_bp)) / Decimal(10000))


def as_number(value):
    """Serialise a Decimal points value as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return float(value)
        return float(value)
    return value


# --------------------------------------------------------------------------
# common-field bookkeeping
# --------------------------------------------------------------------------
def new_row(collection, **fields):
    stamp = iso_ms()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next(_seq),
    }
    row.update(fields)
    collection[row["id"]] = row
    try:
        created = getattr(g, "_created", None)
        if created is None:
            created = set()
            g._created = created
        created.add(row["id"])
    except RuntimeError:  # pragma: no cover - outside a request context
        pass
    return row


def _request_stamp():
    """One shared updated_at value for every row mutated by this request."""
    try:
        stamp = getattr(g, "_stamp", None)
        if stamp is None:
            stamp = iso_ms()
            g._stamp = stamp
        return stamp
    except RuntimeError:  # pragma: no cover - outside a request context
        return iso_ms()


def touch(row):
    """Mark a row as mutated: its version/updated_at advance once per request.

    The bump is applied immediately (so a response serialised later in the same
    request reports the final version) but at most once per row per request.
    Rows created within the same request never advance past version 1.
    """
    if row is None:
        return
    if row["id"] in getattr(g, "_created", ()):  # freshly created this request
        return
    dirty_ids = getattr(g, "_dirty_ids", None)
    if dirty_ids is None:
        dirty_ids = set()
        g._dirty_ids = dirty_ids
    if row["id"] in dirty_ids:
        return
    dirty_ids.add(row["id"])
    row["version"] = int(row["version"]) + 1
    row["updated_at"] = _request_stamp()


def set_value(row, key, value):
    """Assign a recomputed field, marking the row dirty only when it really changed."""
    if row.get(key) != value:
        row[key] = value
        touch(row)


def commit():
    """Retained for symmetry: version bumps are applied eagerly by ``touch``."""
    return None


# --------------------------------------------------------------------------
# lookup helpers
# --------------------------------------------------------------------------
def find(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def division_of_class(cls):
    return db.divisions.get(cls["division_id"])


def show_of_division(division):
    return db.shows.get(division["show_id"]) if division else None


def show_of_class(cls):
    return show_of_division(division_of_class(cls))


def show_of_ring(ring):
    return db.shows.get(ring["show_id"])


def classes_of_division(division_id):
    return [c for c in db.classes.values() if c["division_id"] == division_id]


def classes_of_show(show_id):
    out = []
    for cls in db.classes.values():
        division = db.divisions.get(cls["division_id"])
        if division is not None and division["show_id"] == show_id:
            out.append(cls)
    return out


def divisions_of_show(show_id):
    return [d for d in db.divisions.values() if d["show_id"] == show_id]


def rings_of_show(show_id):
    return [r for r in db.rings.values() if r["show_id"] == show_id]


def slots_of_ring(ring_id):
    return [s for s in db.slots.values() if s["ring_id"] == ring_id]


def slots_of_class(class_id):
    return [s for s in db.slots.values() if s.get("class_id") == class_id]


def class_entries_of_class(class_id):
    return [ce for ce in db.class_entries.values() if ce["class_id"] == class_id]


def class_entries_of_entry(entry_id):
    return [ce for ce in db.class_entries.values() if ce["entry_id"] == entry_id]


def assignments_of_slot(slot_id):
    return [a for a in db.assignments.values() if a["slot_id"] == slot_id]


def assignments_of_official(official_id):
    return [a for a in db.assignments.values() if a["official_id"] == official_id]


def submissions_of_class(class_id):
    return [s for s in db.submissions.values() if s["class_id"] == class_id]


def entries_of_show(show_id):
    return [e for e in db.entries.values() if e["show_id"] == show_id]


def coverage_of_show(show_id):
    return [c for c in db.coverage_shifts.values() if c["show_id"] == show_id]


def entry_of_class_entry(class_entry):
    return db.entries.get(class_entry["entry_id"])


def rider_of_class_entry(class_entry):
    entry = entry_of_class_entry(class_entry)
    return db.riders.get(entry["rider_id"]) if entry else None


def timedelta_minutes(n):
    return timedelta(minutes=int(n))
