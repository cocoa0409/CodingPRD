"""In-memory data store (PRD §2.4 common fields).

All state lives in module-level dicts keyed by id. Nothing is seeded at import:
every entity is created via the API. Re-importing / re-launching the process
yields an empty store.
"""

import uuid
import datetime

# Logical server clock (PRD §3.11). Defaults to real wall-clock UTC until a
# PlatformAdmin sets it via POST /_clock/set_current_utc.
_clock = {"now": None}


def now_dt():
    if _clock["now"] is not None:
        return _clock["now"]
    return datetime.datetime.now(datetime.timezone.utc)


def set_clock(dt):
    _clock["now"] = dt


def iso_now():
    return format_ts(now_dt())


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and 'Z' (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex


# Collections. Each maps id -> record dict.
plans = {}
customers = {}
subscriptions = {}
route_windows = {}
lockers = {}
orders = {}
garments = {}
garment_notes = {}
locker_assignments = {}
claims = {}
invoices = {}


def reset():
    for d in (plans, customers, subscriptions, route_windows, lockers, orders,
              garments, garment_notes, locker_assignments, claims, invoices):
        d.clear()
    _clock["now"] = None
