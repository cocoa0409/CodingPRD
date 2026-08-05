"""In-memory data store, logical clock, and timestamp/money helpers.

Everything lives in process memory only. A fresh process (start.sh re-invoke)
starts with an empty store and the default logical clock. Nothing is seeded.
"""
import math
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # logical clock — an aware UTC datetime; default per PRD, never wall-clock
        self.clock = parse_dt(DEFAULT_CLOCK)
        self._seq = 0
        self.staff_users = {}
        self.clients = {}
        self.job_openings = {}
        self.candidates = {}
        self.applications = {}
        self.site_visits = {}
        self.offers = {}
        self.placements = {}
        self.cred_files = {}
        self.cred_items = {}
        self.reloc_expenses = {}
        self.guarantee_claims = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        return render_clock(self.clock)


# --------------------------------------------------------------------------
# id / request id
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------
def parse_dt(s):
    """Parse an ISO-8601 UTC string into an aware UTC datetime."""
    if s is None:
        return None
    t = str(s).strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_clock(dt):
    """Render an aware datetime as ISO-8601 UTC with exactly three fractional
    digits and a trailing Z (used for all server-minted lifecycle timestamps
    and meta timestamps — always driven by the logical clock, never wall-clock)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _source_has_fraction(s):
    if s is None:
        return False
    tp = str(s).split("T", 1)[1] if "T" in str(s) else str(s)
    return "." in tp


def render_like(dt, source):
    """Render a *computed* domain datetime derived from a client-supplied input
    date so that its string form matches the input's style (plain 'Z' vs
    '.mmmZ'). This keeps generated domain dates in the same format the input
    dates are echoed in — avoids the '.000Z' vs plain 'Z' mismatch."""
    dt = dt.astimezone(timezone.utc)
    if _source_has_fraction(source):
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(source_str, days):
    """source_str + whole days, rendered in the same format as source_str."""
    base = parse_dt(source_str)
    result = base + timedelta(days=int(days))
    return render_like(result, source_str)


def whole_days_between(start_str, end_str):
    """floor((end - start) in whole days)."""
    a = parse_dt(start_str)
    b = parse_dt(end_str)
    return int(math.floor((b - a).total_seconds() / 86400.0))


# --------------------------------------------------------------------------
# money helpers — integer cents, round half up
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to whole units, half up, returning int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(v):
    return Decimal(str(v))


# Instantiated after all helpers are defined (reset() uses parse_dt).
S = Store()
