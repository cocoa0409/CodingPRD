"""In-memory data store. Empty at every boot — no seeding whatsoever."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_now = _CLOCK_START


def clock_now():
    return _logical_now


def set_clock(dt):
    global _logical_now
    _logical_now = dt
    return _logical_now


# ---------------------------------------------------------------------------
# Stores: dicts keyed by id. Insertion order preserved (Python 3.7+).
# ---------------------------------------------------------------------------

programs = {}
sites = {}
host_agreements = {}
materials = {}
participants = {}
grants = {}
drops = {}
contamination_reports = {}
routes = {}
partners = {}
stops = {}
batches = {}
distributions = {}
allocations = {}
complaints = {}
diversion_reports = {}

# Credit grant ledger entries: list of dicts recording each credit grant event
# for FIFO redemption/expiry. Each entry:
#   { participant_id, amount, occurred_at (drop occurred_at), created_at,
#     drop_id, remaining }
credit_ledger = []


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def fmt_ts(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO8601 string to an aware datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_kg(value):
    """Round a numeric value half-up to 2 decimal places, returning float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def round_kg_dec(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_credit(value):
    """Round half-up to a whole integer credit."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)
