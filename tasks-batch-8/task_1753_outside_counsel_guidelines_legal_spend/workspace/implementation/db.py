"""In-memory data store, logical clock, and ID/timestamp helpers.

The store starts EMPTY on every boot — no seeding. Tests construct every
entity through the declared API surface.
"""

import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# The single logical-clock instant. Never falls back to wall-clock time.
_logical_clock = datetime(2026, 8, 1, tzinfo=timezone.utc)


def get_clock() -> datetime:
    return _logical_clock


def set_clock(dt: datetime) -> datetime:
    global _logical_clock
    _logical_clock = dt
    return _logical_clock


def now_iso() -> str:
    """Logical clock as ISO-8601 UTC with three fractional digits."""
    return format_iso(_logical_clock)


def format_iso(dt: datetime) -> str:
    """ISO-8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(s):
    """Parse an ISO-8601 datetime/date string into an aware UTC datetime.

    Accepts trailing 'Z' or numeric offsets, and bare dates (interpreted as
    midnight UTC). Returns None if the value cannot be parsed.
    """
    if s is None:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        text = str(s).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            # Try bare date
            try:
                dt = datetime.strptime(str(s).strip()[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def new_id() -> str:
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Request identifier starting with 'req_' (PRD §2.2)."""
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(24))
    return f"req_{suffix}"


# ---------------------------------------------------------------------------
# Entity stores — plain dicts keyed by id. Start EMPTY on every boot.
# ---------------------------------------------------------------------------

legal_departments: dict = {}
panel_firms: dict = {}
guideline_versions: dict = {}
guideline_acknowledgments: dict = {}
matters: dict = {}
rate_cards: dict = {}
timekeepers: dict = {}
timekeeper_rates: dict = {}
invoices: dict = {}
invoice_line_items: dict = {}
appeals: dict = {}
accruals: dict = {}
matter_forecasts: dict = {}   # keyed by matter_id (1:1 with Matter)
scorecard_snapshots: dict = {}

# Monotonic creation counter used as a stable tie-break for equal timestamps.
_creation_counter = [0]


def next_creation_seq() -> int:
    _creation_counter[0] += 1
    return _creation_counter[0]


def base_resource(extra: dict = None) -> dict:
    """Common resource properties per PRD §2.4."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_creation_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec: dict):
    """Refresh updated_at and bump version by one (PRD §2.4, §2.10)."""
    rec["updated_at"] = now_iso()
    rec["version"] = int(rec.get("version", 1)) + 1
