"""In-memory data store, logical clock, and row primitives.

The store starts completely empty on every boot; nothing is seeded.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from response import wall_iso

LOCK = threading.RLock()

COLLECTIONS = (
    "centers",
    "chairs",
    "nurses",
    "drugs",
    "lots",
    "patients",
    "plans",
    "templates",
    "appointments",
    "auths",
    "preps",
    "events",
    "labs",
    "reminders",
)

NOT_FOUND = {
    "centers": "ERR_CENTER_NOT_FOUND",
    "chairs": "ERR_CHAIR_NOT_FOUND",
    "nurses": "ERR_NURSE_NOT_FOUND",
    "drugs": "ERR_DRUG_NOT_FOUND",
    "lots": "ERR_LOT_NOT_FOUND",
    "patients": "ERR_PATIENT_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "templates": "ERR_TEMPLATE_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "auths": "ERR_AUTHORIZATION_NOT_FOUND",
    "preps": "ERR_PREPARATION_NOT_FOUND",
    "events": "ERR_ADVERSE_EVENT_NOT_FOUND",
    "labs": "ERR_LAB_RESULT_NOT_FOUND",
    "reminders": "ERR_REMINDER_NOT_FOUND",
}

DB = {name: {} for name in COLLECTIONS}

DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
CLOCK = {
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": DEFAULT_CLOCK_RAW,
}

_SEQ = itertools.count(1)


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------
def now():
    """The logical clock as an aware UTC datetime."""
    return CLOCK["dt"]


def clock_raw():
    return CLOCK["raw"]


def set_clock(dt, raw):
    previous = CLOCK["raw"]
    CLOCK["dt"] = dt
    CLOCK["raw"] = raw
    return previous


def clock_date():
    return now().date()


def clock_minute_of_day():
    d = now()
    return d.hour * 60 + d.minute


def iso_ms(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def midnight(service_date):
    """Midnight UTC of a YYYY-MM-DD string or date object."""
    if isinstance(service_date, str):
        y, m, d = service_date.split("-")
        return datetime(int(y), int(m), int(d), tzinfo=timezone.utc)
    return datetime(service_date.year, service_date.month, service_date.day, tzinfo=timezone.utc)


def instant_of(service_date, minute):
    return midnight(service_date) + timedelta(minutes=int(minute or 0))


# --------------------------------------------------------------------------
# rounding helpers
# --------------------------------------------------------------------------
def rhu(value, places):
    """Round half up to the requested number of decimal places, as Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def two_dp(value):
    """Two-decimal round-half-up rendered as a JSON number."""
    return float(rhu(value, 2))


def one_dp(value):
    return float(rhu(value, 1))


def ceil_div(numerator, denominator):
    return -((-int(numerator)) // int(denominator))


# --------------------------------------------------------------------------
# row primitives
# --------------------------------------------------------------------------
def new_row(collection, fields, versioned=True):
    row_id = str(uuid.uuid4())
    row = {"id": row_id, "created_at": wall_iso()}
    row.update(fields)
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next(_SEQ)
    DB[collection][row_id] = row
    return row


def touch(row):
    row["version"] = int(row.get("version", 1)) + 1
    row["updated_at"] = wall_iso()


def apply_changes(row, changes):
    """Apply a field change-set; bump version/updated_at exactly once if anything moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            changed = True
        row[key] = value
    if changed:
        touch(row)
    return changed


def rows(collection):
    """All rows of a collection in created_at (insertion) order."""
    return sorted(DB[collection].values(), key=lambda r: r["_seq"])


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


def must(collection, row_id):
    row = get(collection, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}
