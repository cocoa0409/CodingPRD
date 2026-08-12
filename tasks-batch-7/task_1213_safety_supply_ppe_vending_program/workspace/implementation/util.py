import random
import string
import uuid
from datetime import date, datetime, timezone

import db


def new_id():
    return str(uuid.uuid4())


def req_id(n=20):
    return "req_" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_iso3():
    return iso3(datetime.now(timezone.utc))


def now_iso():
    """Entity timestamps follow the logical clock (platform never uses wall-clock)."""
    return iso3(db.clock)


def parse_datetime(s):
    """Parse an ISO 8601 date or datetime into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("must be a string")
    t = s.strip()
    if len(t) == 10 and t[4] == "-" and t[7] == "-":
        return datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    iso = t[:-1] + "+00:00" if t.endswith("Z") else t
    d = datetime.fromisoformat(iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO 8601 date (or datetime; date part taken) into a date."""
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    return parse_datetime(s).date()


def is_date_str(s):
    try:
        parse_date(s)
        return True
    except Exception:
        return False


def is_datetime_str(s):
    try:
        parse_datetime(s)
        return True
    except Exception:
        return False


def clock_date():
    return db.clock.date()


def render_clock():
    dt = db.clock
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso3(dt)


def serialize(v):
    """Recursively render a record: strip internal '_' keys, format dates."""
    if isinstance(v, dict):
        return {k: serialize(val) for k, val in v.items() if not k.startswith("_")}
    if isinstance(v, list):
        return [serialize(x) for x in v]
    if isinstance(v, datetime):
        return iso3(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def touch(rec):
    """Mutation bookkeeping: refresh updated_at, increment version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1


def new_record(fields):
    """Build a new entity dict with common system fields."""
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec
