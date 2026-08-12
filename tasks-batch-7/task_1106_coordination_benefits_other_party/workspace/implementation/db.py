"""In-memory data store. Store starts empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def now_dt():
    return clock.now()


def now_iso():
    return iso_fmt(clock.now())


def iso_fmt(dt):
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_iso(s):
    """Parse an ISO 8601 timestamp or date into an aware datetime (UTC)."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    # Date-only form YYYY-MM-DD
    if len(txt) == 10 and txt[4] == "-" and txt[7] == "-":
        return datetime.strptime(txt, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO date (YYYY-MM-DD) or timestamp into a date."""
    if isinstance(s, str) and len(s) == 10:
        return datetime.strptime(s, "%Y-%m-%d").date()
    return parse_iso(s).date()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# Stores: plain dicts keyed by id. Empty at boot.
# ---------------------------------------------------------------------------

stores = {
    "rule_configs": {},
    "members": {},
    "coverages": {},
    "leads": {},
    "determinations": {},
    "questionnaires": {},
    "claims": {},
    "claim_lines": {},
    "adjustments": {},
    "providers": {},
    "recovery_requests": {},
    "reimbursements": {},
    "savings_periods": {},
    "surveys": {},
}
