"""In-memory store, logical clock and the per-request version/audit machinery.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every entity is created through the declared API surface.
"""
import re
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal

import config

# ------------------------------------------------------------------ collections
affiliates = {}
agreements = {}
reviews = {}
staff_members = {}
allocations = {}
players = {}
assignments = {}
plans = {}
workload_logs = {}
clearances = {}
option_years = {}
pools = {}
signings = {}
reports = {}

COLLECTIONS = {
    "affiliates": affiliates,
    "agreements": agreements,
    "reviews": reviews,
    "staff_members": staff_members,
    "allocations": allocations,
    "players": players,
    "assignments": assignments,
    "plans": plans,
    "workload_logs": workload_logs,
    "clearances": clearances,
    "option_years": option_years,
    "pools": pools,
    "signings": signings,
    "reports": reports,
}

# ----------------------------------------------------------------- logical clock
_CLOCK = {"current": datetime(2026, 8, 1, 0, 0, 0, 0)}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def request_id():
    raw = uuid.uuid4().hex.upper()
    return "req_" + raw[:20]


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def clock_now():
    return _CLOCK["current"]


def now_iso():
    return fmt_dt(_CLOCK["current"])


def clock_date():
    return _CLOCK["current"].date()


def set_clock(dt):
    _CLOCK["current"] = dt


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Strict YYYY-MM-DD -> date, or None when unparseable."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_iso(value):
    """ISO 8601 instant -> naive UTC datetime, or None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        offset = dt.utcoffset()
        dt = dt.replace(tzinfo=None)
        if offset:
            dt = dt - offset
    return dt


def days_between(from_date, to_date):
    """Whole-day interval to_date - from_date."""
    return (to_date - from_date).days


def add_days(d, n):
    return d + timedelta(days=n)


def iso_date(d):
    return d.isoformat()


# ----------------------------------------------------------- audit / versioning
_SNAPSHOT = {"data": None}


def _public(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_") or k in ("updated_at", "version"):
            continue
        out[k] = list(v) if isinstance(v, list) else v
    return out


def begin_request():
    snap = {}
    for name, coll in COLLECTIONS.items():
        for rid, rec in coll.items():
            snap[(name, rid)] = _public(rec)
    _SNAPSHOT["data"] = snap


def touch(rec):
    """Force a version bump for this record even if no field value changed."""
    if rec is not None:
        rec["_forced"] = True


def finalize_request():
    """Bump version / updated_at on every record whose observable state moved."""
    snap = _SNAPSHOT["data"] or {}
    for name, coll in COLLECTIONS.items():
        for rid, rec in coll.items():
            forced = rec.pop("_forced", False)
            if rec.pop("_new", False):
                continue
            if "version" not in rec:
                continue
            old = snap.get((name, rid))
            if old is None:
                continue
            if forced or _public(rec) != old:
                rec["version"] += 1
                rec["updated_at"] = now_iso()
    _SNAPSHOT["data"] = None


def rollback_request():
    """Discard every write the failed request made (nothing is written on error)."""
    snap = _SNAPSHOT["data"]
    if snap is None:
        return
    for name, coll in COLLECTIONS.items():
        for rid in list(coll.keys()):
            old = snap.get((name, rid))
            if old is None:
                del coll[rid]
            else:
                coll[rid].update(old)
                coll[rid].pop("_forced", None)
                coll[rid].pop("_new", None)
    _SNAPSHOT["data"] = None


def base_record():
    """id / created_at / updated_at / version quartet."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "_new": True,
    }


def base_event_record():
    """Append-only event: id + created_at only (no updated_at, no version)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "_new": True,
    }


def sorted_rows(rows):
    """Default list ordering: created_at ascending, stable on insertion order."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
