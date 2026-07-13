"""In-memory data store. Starts EMPTY on every boot: nothing is seeded."""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

import config

# ---------------------------------------------------------------- collections
accounts = {}
domains = {}
dns_records = {}
hosting_plans = {}
subscriptions = {}
add_ons = {}
transfer_requests = {}
invoices = {}
line_items = {}
ledger_entries = {}
billing_periods = {}
usage_records = {}
abuse_reports = {}
promo_codes = {}

ALL_COLLECTIONS = (
    accounts,
    domains,
    dns_records,
    hosting_plans,
    subscriptions,
    add_ons,
    transfer_requests,
    invoices,
    line_items,
    ledger_entries,
    billing_periods,
    usage_records,
    abuse_reports,
    promo_codes,
)

_seq = itertools.count(1)

# ------------------------------------------------------------- logical clock
_clock = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt.astimezone(timezone.utc)
    return _clock["now"]


# ------------------------------------------------------------------- helpers
def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 instant. Raises ValueError when unparseable."""
    if not isinstance(value, str) or not value:
        raise ValueError("not a datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_seq():
    return next(_seq)


def base_record(with_audit=True):
    """id + created_at (+ updated_at / version when the entity carries the audit triple)."""
    now = wall_now()
    rec = {
        "id": new_id(),
        "created_at": fmt_dt(now),
        "_seq": next_seq(),
        "_created": now,
    }
    if with_audit:
        rec["updated_at"] = fmt_dt(now)
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version (used by direct writes AND cascades)."""
    rec["updated_at"] = fmt_dt(wall_now())
    rec["version"] = rec.get("version", 1) + 1
    return rec


def ordered(collection, predicate=None):
    """Rows in created_at ASC order (insertion order, tie-free)."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def mint_code(length=16):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def days(n):
    return timedelta(days=n)


def years(n):
    return timedelta(days=n * config.DAYS_PER_YEAR)
