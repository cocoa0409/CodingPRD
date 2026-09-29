"""In-memory data store, logical clock and record helpers.

Storage is process-local Python dicts keyed by uuid string.  Nothing is
persisted and nothing is seeded: the store starts empty on every boot.
"""
import copy
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from errors import ApiError

TABLE_NAMES = [
    "outfitters",
    "use_areas",
    "needs_assessments",
    "prospectuses",
    "applications",
    "permits",
    "operating_plans",
    "guides",
    "authorizations",
    "insurance_certificates",
    "bonds",
    "use_reports",
    "fee_assessments",
    "performance_evaluations",
    "noncompliance_actions",
]

TABLES = {name: {} for name in TABLE_NAMES}

DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
CLOCK = {
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": DEFAULT_CLOCK_RAW,
}
SEQ = {"n": 0}


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, error_id="ERR_INVALID_REQUEST", field=None):
    """Parse an ISO-8601 date or date-time into an aware UTC datetime."""
    if isinstance(value, datetime):
        d = value
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(error_id, "invalid date-time for %s" % (field or "field"))
    raw = value.strip()
    text = raw
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        try:
            d = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            raise ApiError(error_id, "invalid date-time for %s" % (field or "field"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def now_dt():
    return CLOCK["dt"]


def now_raw():
    return CLOCK["raw"]


def now_str():
    return fmt_dt(CLOCK["dt"])


def today():
    return CLOCK["dt"].date()


def set_clock(dt, raw):
    CLOCK["dt"] = dt
    CLOCK["raw"] = raw


def as_date(value):
    """Date part of an arbitrary stored/incoming date-time value."""
    if value is None:
        return None
    return parse_dt(value).date()


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def insert(table, fields, common=True):
    SEQ["n"] += 1
    rec = dict(fields)
    rec["id"] = new_id()
    rec["_table"] = table
    rec["_seq"] = SEQ["n"]
    rec["created_at"] = now_str()
    rec["_created_dt"] = now_dt()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    TABLES[table][rec["id"]] = rec
    return rec


def touch(rec):
    """Advance updated_at/version at most once per request for this record."""
    if rec is None:
        return rec
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = (rec.get("_table"), rec.get("id"))
    if key in touched:
        return rec
    touched.add(key)
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1
    if "updated_at" in rec:
        rec["updated_at"] = now_str()
    return rec


def get(table, rec_id):
    if not isinstance(rec_id, str):
        return None
    return TABLES[table].get(rec_id)


def get_or_404(table, rec_id, error_id):
    rec = get(table, rec_id)
    if rec is None:
        raise ApiError(error_id, "%s not found" % table[:-1])
    return rec


def all_of(table):
    return list(TABLES[table].values())


def where(table, **kwargs):
    out = []
    for rec in TABLES[table].values():
        ok = True
        for key, val in kwargs.items():
            if isinstance(val, (list, tuple, set, frozenset)):
                if rec.get(key) not in val:
                    ok = False
                    break
            elif rec.get(key) != val:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def sort_created(records, descending=False):
    return sorted(
        records, key=lambda r: (r["_created_dt"], r["_seq"]), reverse=descending
    )


def sort_by(records, keys, descending=False):
    """Sort by a list of (accessor) callables, then created_at ASC, then seq."""

    def keyfn(rec):
        return tuple(fn(rec) for fn in keys) + (rec["_created_dt"], rec["_seq"])

    return sorted(records, key=keyfn, reverse=descending)


# --------------------------------------------------------------------------
# transactional snapshot -- a rejected request must write nothing at all
# --------------------------------------------------------------------------
def begin(mutating):
    g.touched = set()
    if mutating:
        g.snapshot = {name: copy.deepcopy(tbl) for name, tbl in TABLES.items()}
        g.clock_snapshot = dict(CLOCK)
        g.seq_snapshot = SEQ["n"]
    else:
        g.snapshot = None


def rollback():
    snap = getattr(g, "snapshot", None)
    if snap is None:
        return
    for name, tbl in snap.items():
        TABLES[name].clear()
        TABLES[name].update(tbl)
    CLOCK.update(getattr(g, "clock_snapshot", CLOCK))
    SEQ["n"] = getattr(g, "seq_snapshot", SEQ["n"])
    g.snapshot = None


def reset_all():
    for tbl in TABLES.values():
        tbl.clear()
    SEQ["n"] = 0
    CLOCK["dt"] = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    CLOCK["raw"] = DEFAULT_CLOCK_RAW
