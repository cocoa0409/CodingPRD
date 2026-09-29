"""In-memory data store, logical clock, and time helpers."""
import calendar
import itertools
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------- collections
prescriptions = {}
circuits = {}
work_plans = {}
work_orders = {}
crews = {}
crew_assignments = {}
production_entries = {}
customer_notifications = {}
hazard_trees = {}
herbicide_permits = {}
storm_events = {}
billing_lines = {}
outage_records = {}

_seq = itertools.count(1)
_clock = {"now": DEFAULT_CLOCK}


def reset():
    for coll in (prescriptions, circuits, work_plans, work_orders, crews,
                 crew_assignments, production_entries, customer_notifications,
                 hazard_trees, herbicide_permits, storm_events, billing_lines,
                 outage_records):
        coll.clear()
    _clock["now"] = DEFAULT_CLOCK


# ---------------------------------------------------------------- clock
def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(now())


def today_str():
    return now().astimezone(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- parsing
def parse_datetime(value):
    """Parse an ISO-8601 datetime; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date string; returns None when unparseable."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def add_calendar_months(date_str, months):
    """Advance a YYYY-MM-DD date by N calendar months, clamping the day."""
    d = parse_date(date_str) if isinstance(date_str, str) else date_str
    if d is None:
        return None
    total = (d.year * 12 + (d.month - 1)) + int(months)
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return d.replace(year=year, month=month, day=min(d.day, last_day))


def shift_months_dt(dt, months):
    """Advance a datetime by N calendar months, clamping the day."""
    total = (dt.year * 12 + (dt.month - 1)) + int(months)
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


# ---------------------------------------------------------------- records
def new_record(common=True):
    stamp = now_iso()
    rec = {"id": str(uuid.uuid4()), "created_at": stamp, "_seq": next(_seq)}
    if common:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    if rec is None:
        return rec
    if "version" in rec:
        rec["version"] = int(rec["version"]) + 1
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()
    return rec


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(values):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(values, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
