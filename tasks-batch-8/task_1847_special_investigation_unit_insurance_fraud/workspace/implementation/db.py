"""In-memory data store for the SIU Fraud API.

The store starts completely empty on every boot — nothing is seeded. Tests
build all state through the declared API surface.

The logical clock (PRD §2.10) is deterministic: it starts at
2026-08-01T00:00:00Z and moves only via POST /siu/_clock/set_current_utc.
Every business-rule "now" — deadlines, windows, created_at/updated_at — is
taken from this clock, never from the host wall clock.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from constants import CLOCK_DEFAULT

# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

claims: dict[str, dict] = {}
adjusters: dict[str, dict] = {}
referrals: dict[str, dict] = {}
cases: dict[str, dict] = {}
investigators: dict[str, dict] = {}
assignments: dict[str, dict] = {}
evidence: dict[str, dict] = {}
euo_sessions: dict[str, dict] = {}
bureau_referrals: dict[str, dict] = {}
provider_patterns: dict[str, dict] = {}
ledgers: dict[str, dict] = {}
payments: dict[str, dict] = {}
training_records: dict[str, dict] = {}
reports: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Ids, insertion sequence, case numbers
# ---------------------------------------------------------------------------

_seq = [0]
_case_seq = [0]


def next_seq() -> int:
    _seq[0] += 1
    return _seq[0]


def new_id() -> str:
    return str(uuid.uuid4())


def mint_case_number(now: datetime) -> str:
    """SIU-YYYY-NNNNNN; year from the logical clock, NNNNNN a global sequence."""
    _case_seq[0] += 1
    return "SIU-{:04d}-{:06d}".format(now.year, _case_seq[0])


# ---------------------------------------------------------------------------
# ISO 8601 parsing / rendering
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ]"
    r"(\d{2}):(\d{2})(?::(\d{2}))?"
    r"(?:\.(\d{1,9}))?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO 8601 instant to an aware UTC datetime, or None if malformed."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        bodytext = offset[1:].replace(":", "")
        delta = timedelta(hours=int(bodytext[:2]), minutes=int(bodytext[2:4]))
        dt = dt - sign * delta
    return dt.astimezone(timezone.utc)


def render_server(dt) -> str:
    """Server-written instant: ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000
    )


def render_deadline(dt) -> str:
    """Deadline/window-computation instant (PRD §2.9): second precision, no
    fractional digits — e.g. investigation_deadline_at, decision_due_at, and the
    bureau referral's deadline_at."""
    if dt is None:
        return None
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
    )


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


class LogicalClock:
    """Never reads wall-clock time. Starts at the PRD-declared default instant."""

    def __init__(self) -> None:
        self._now = parse_instant(CLOCK_DEFAULT)
        self._raw = CLOCK_DEFAULT

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def raw(self) -> str:
        """The operator-supplied to_iso8601 string, verbatim."""
        return self._raw

    def set(self, dt: datetime, raw: str) -> None:
        self._now = dt
        self._raw = raw

    def now_string(self) -> str:
        return render_server(self._now)


clock = LogicalClock()


# ---------------------------------------------------------------------------
# Mutation bookkeeping
#
# PRD §2.4: every mutation refreshes updated_at and increments version by one.
# A given row is bumped at most once per API request, however many cascade hops
# touch it; rows created by the request stay at version 1.
# ---------------------------------------------------------------------------


def _touched():
    try:
        from flask import g, has_request_context

        if has_request_context():
            if not hasattr(g, "_siu_touched"):
                g._siu_touched = set()
            return g._siu_touched
    except Exception:
        pass
    return set()


def stamp_new(row: dict) -> dict:
    ts = clock.now_string()
    row["id"] = new_id()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row) -> None:
    """Refresh updated_at; bump version unless this request already bumped it."""
    if row is None or "version" not in row:
        return
    row["updated_at"] = clock.now_string()
    seen = _touched()
    key = id(row)
    if key in seen:
        return
    seen.add(key)
    row["version"] = int(row.get("version", 1)) + 1
