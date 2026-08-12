import uuid
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_iso():
    return fmt_dt(db.clock())


def clock_date():
    return db.clock().date()


def parse_datetime(s):
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def dec(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def rhu(x):
    """Round half up to whole cents -> int."""
    return int(dec(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_resource(fields=None, versioned=True):
    r = {"id": new_id(), "created_at": now_iso(), "_seq": db.next_seq()}
    if versioned:
        r["updated_at"] = r["created_at"]
        r["version"] = 1
    if fields:
        r.update(fields)
    return r


def touch(r):
    r["updated_at"] = now_iso()
    r["version"] = int(r.get("version", 1)) + 1


# ---- request shape validators (all raise ERR_INVALID_REQUEST / 400) ----

def bad(msg):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def req(d, name):
    if not isinstance(d, dict) or name not in d or d[name] is None:
        raise bad("{} is required".format(name))
    return d[name]


def opt(d, name, default=None):
    if not isinstance(d, dict):
        return default
    v = d.get(name, default)
    return default if v is None else v


def as_str(v, name):
    if not isinstance(v, str):
        raise bad("{} must be a string".format(name))
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad("{} must be an integer".format(name))
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad("{} must be a number".format(name))
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise bad("{} must be a boolean".format(name))
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise bad("{} must be one of {}".format(name, sorted(allowed)))
    return v


def as_list(v, name):
    if not isinstance(v, list):
        raise bad("{} must be an array".format(name))
    return v


def as_date_str(v, name):
    as_str(v, name)
    if parse_date(v) is None:
        raise bad("{} must be an ISO date".format(name))
    return v


def as_datetime_str(v, name):
    as_str(v, name)
    if parse_datetime(v) is None:
        raise bad("{} must be an ISO datetime".format(name))
    return v
