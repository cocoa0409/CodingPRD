"""In-memory data store + logical clock for the Fiscal Sponsorship Administration API.

Storage is in-memory only: plain dicts keyed by id. The store starts empty on
every boot; nothing is seeded. The server never consults wall-clock time — all
timestamps derive from the logical clock (PRD §2.4), whose startup value is
exactly 2026-05-01T00:00:00Z.
"""

import secrets
import threading
import uuid
from datetime import date, datetime, timezone

from flask import g


class Store:
    def __init__(self):
        self.applications = {}
        self.projects = {}
        self.agreements = {}
        self.funds = {}
        self.donations = {}
        self.receipts = {}
        self.disbursements = {}
        self.engagements = {}
        self.reviews = {}
        self.incidents = {}
        self.exit_plans = {}
        self.tranches = {}
        self.assessments = {}
        self.ledger_entries = {}
        self.receipt_seq = {}  # tax_year -> last issued sequence (int)
        self.seq = 0           # global insertion counter (stable created_at tie-break)


store = Store()

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

_CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_lock = threading.Lock()
_current_utc = _CLOCK_START


def now():
    with _clock_lock:
        return _current_utc


def set_clock(dt):
    global _current_utc
    with _clock_lock:
        _current_utc = dt


def today():
    return now().date()


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Identity / request helpers
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + secrets.token_hex(8)


def next_seq():
    store.seq += 1
    return store.seq


def stamp_new(ent):
    """Common fields on creation (PRD §2.5)."""
    ts = iso(now())
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = next_seq()
    return ent


def touch(ent):
    """Mutation bookkeeping: version +1 once per request per entity; updated_at
    refreshes on every touch. FundLedgerEntry is exempt (no version/updated_at)."""
    if "version" not in ent:
        return
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if ent["id"] not in touched:
        ent["version"] += 1
        touched.add(ent["id"])
    ent["updated_at"] = iso(now())


def public(ent):
    """Strip internal bookkeeping keys (anything starting with '_')."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookups used across modules
# ---------------------------------------------------------------------------


def fund_of_project(project_id):
    for f in store.funds.values():
        if f["project_id"] == project_id:
            return f
    return None


def agreement_of_project(project_id):
    for a in store.agreements.values():
        if a["project_id"] == project_id:
            return a
    return None


def parse_iso_date(s):
    """Parse a YYYY-MM-DD date string; returns a datetime.date or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_iso_datetime(s):
    """Parse an ISO 8601 UTC datetime; returns an aware datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
