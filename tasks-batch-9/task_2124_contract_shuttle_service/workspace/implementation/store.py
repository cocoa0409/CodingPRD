"""In-memory data store, id/timestamp minting and the logical service clock.

Everything lives in plain python dicts keyed by id.  Nothing is persisted and
nothing is seeded: a fresh process starts with an entirely empty store.
"""

import datetime as _dt
import itertools
import random
import string
import threading
import uuid

from flask import g

LOCK = threading.RLock()

# ---------------------------------------------------------------- collections
contracts = {}
routes = {}
vehicles = {}
drivers = {}
trips = {}
ridership_counts = {}
on_demand_requests = {}
maintenance_orders = {}
service_period_reports = {}
credit_memos = {}
renewal_offers = {}

_seq_counter = itertools.count(1)

# ------------------------------------------------------------- logical clock
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
_clock = {"instant": _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc),
          "raw": CLOCK_EPOCH}


def clock_now():
    return _clock["instant"]


def clock_raw():
    return _clock["raw"]


def clock_service_date():
    """The UTC calendar date of the logical clock, as YYYY-MM-DD."""
    return _clock["instant"].date().isoformat()


def set_clock(instant, raw):
    _clock["instant"] = instant
    _clock["raw"] = raw


# --------------------------------------------------------------- primitives
def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real UTC wall clock, ISO 8601 with exactly three fractional digits."""
    now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _touched_set():
    s = getattr(g, "_touched_rows", None)
    if s is None:
        s = set()
        g._touched_rows = s
    return s


def base_row(with_version=True):
    row = {"id": new_id(), "created_at": now_iso()}
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next(_seq_counter)
    return row


def register_new(row):
    """A freshly created row counts as already 'touched' for this request, so a
    same-request derived recompute does not push its version past 1."""
    _touched_set().add(row["id"])
    return row


def touch(row):
    """Mutate bookkeeping: refresh updated_at and bump version at most once per
    row per request (PRD 2.4 / 2.7)."""
    if "version" not in row:
        return row
    row["updated_at"] = now_iso()
    seen = _touched_set()
    if row["id"] not in seen:
        seen.add(row["id"])
        row["version"] += 1
    return row


def public(row):
    """Strip internal bookkeeping keys from a row for serialisation."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_key_created(row):
    return (row["created_at"], row["_seq"])
