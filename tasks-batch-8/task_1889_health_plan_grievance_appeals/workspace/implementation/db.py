"""In-memory data store and logical server clock.

All state lives in module-level dicts keyed by id. Nothing is persisted to
disk; every process restart (start.sh invocation) starts from an empty store.
No entity is seeded at startup.
"""

import re
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical server clock (PRD section 2.4)
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
_clock_now = None  # datetime, tz-aware UTC


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    return _clock_now


def clock_set(dt):
    global _clock_now
    _clock_now = dt


def clock_reset():
    clock_set(parse_iso(_CLOCK_DEFAULT))


clock_reset()


# ---------------------------------------------------------------------------
# Entity stores (all in-memory, keyed by id; empty at boot)
# ---------------------------------------------------------------------------

members = {}
providers = {}
policies = {}
cases = {}
events = {}
reviews = {}
notifications = {}
referrals = {}
effectuations = {}
reopenings = {}
audit_records = {}

# monotonic creation sequence for deterministic ordering
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def make_common():
    """Common system fields for primary resources (PRD section 2.5)."""
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def make_append_only():
    """CaseEvent / AuditUniverseRecord carry only id and created_at."""
    return {
        "id": new_id(),
        "created_at": clock_now(),
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version for a mutation."""
    entity["updated_at"] = clock_now()
    entity["version"] += 1


# Valid role names (PRD section 2.1)
ROLES = {
    "PlatformAdmin",
    "IntakeSpecialist",
    "CaseAnalyst",
    "MedicalDirector",
    "MemberServicesRep",
    "ComplianceOfficer",
    "ClaimsProcessor",
}

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
