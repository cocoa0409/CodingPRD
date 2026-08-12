"""In-memory store. Everything lives in module-level dicts keyed by id.

The store starts EMPTY on every boot: no seeding, no disk persistence, no
preloading. The logical clock starts at exactly 2026-05-01T00:00:00Z and is
advanced only via POST /api/_clock/set_current_utc.
"""
import itertools
from datetime import timezone

from util import _CLOCK_DEFAULT

# entity tables: id -> row (dict)
cases = {}
allegations = {}
plans = {}
subjects = {}
notices = {}
scopes = {}
evidence_items = {}
interviews = {}
designations = {}
findings = {}
recommendations = {}
reports = {}
disclosures = {}
remediations = {}
alerts = {}

# monotonically increasing insertion counter (deterministic tie-break for
# created_at, which is whole-second logical-clock time and may tie)
_seq = itertools.count(1)

# case_number creation sequence per calendar year: year -> count
case_number_seq = {}

# logical clock (single source of truth for all deadline/window/stamp rules)
_clock = {"now": _CLOCK_DEFAULT}

# idempotency: key -> {"fp": fingerprint, "status": int, "body": str}
idempotency = {}


def next_seq():
    return next(_seq)


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt.astimezone(timezone.utc).replace(microsecond=0)


def next_case_number(year):
    n = case_number_seq.get(year, 0) + 1
    case_number_seq[year] = n
    return f"INV-{year}-{n:04d}"
