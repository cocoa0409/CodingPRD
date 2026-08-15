"""In-memory data store. Everything lives in module-level dicts keyed by id.

The store starts completely empty on every boot — no seeding, no preloading.
The logical clock starts at exactly 2026-08-01T00:00:00Z per PRD §2.11.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity stores (all empty at boot)
# ---------------------------------------------------------------------------
trust_funds = {}
employers = {}
apprentices = {}
contribution_reports = {}
training_classes = {}
class_enrollments = {}
instructor_pay_claims = {}
funding_allocations = {}
equipment_purchases = {}

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.11)
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
_clock_iso = _DEFAULT_CLOCK_ISO


def _parse_iso(s):
    """Parse an ISO-8601 string (accepting trailing Z) into an aware datetime."""
    if isinstance(s, str):
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError("not an iso string")


def get_clock():
    """Current logical time as an aware UTC datetime."""
    return _parse_iso(_clock_iso)


def get_clock_iso():
    return _clock_iso


def set_clock(iso_str):
    global _clock_iso
    dt = _parse_iso(iso_str)
    _clock_iso = format_iso(dt)
    return _clock_iso


# ---------------------------------------------------------------------------
# ID / timestamp helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def format_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock timestamp for created_at / updated_at (three fractional digits)."""
    return format_iso(datetime.now(timezone.utc))
