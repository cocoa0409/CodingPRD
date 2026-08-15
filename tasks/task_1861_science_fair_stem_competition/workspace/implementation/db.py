"""In-memory data store and logical clock.

The store starts empty on every boot -- no seeding of any kind.
All timestamps the business logic reads come from the logical clock,
which starts at 2026-08-01T00:00:00Z and only advances via the
FairDirector-only test-driving endpoint.
"""

import uuid
from datetime import datetime, timezone
import threading

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
_logical_clock = _DEFAULT_CLOCK


def clock_now_iso():
    """Return current logical clock reading (ISO 8601 with Z suffix)."""
    with _LOCK:
        return _logical_clock


def clock_set_iso(to_iso8601):
    """Set the logical clock to the given ISO 8601 string."""
    global _logical_clock
    with _LOCK:
        _logical_clock = to_iso8601


def parse_iso(s):
    """Parse an ISO 8601 string into an aware datetime for comparison.

    Accepts forms like '2026-08-01T00:00:00Z' or with fractional seconds
    and/or explicit offsets.
    """
    if s is None:
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def now_display_iso():
    """Timestamp for created_at/updated_at fields: logical clock reading
    rendered as ISO 8601 UTC with three fractional digits."""
    cur = clock_now_iso()
    dt = parse_iso(cur)
    base = dt.astimezone(timezone.utc)
    return base.strftime("%Y-%m-%dT%H:%M:%S.") + f"{base.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------

_req_counter = 0
_req_lock = threading.Lock()


def new_request_id():
    global _req_counter
    with _req_lock:
        _req_counter += 1
        return f"req_{uuid.uuid4().hex[:20]}"


# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id)
# ---------------------------------------------------------------------------

fair_editions = {}
categories = {}
mentors = {}
projects = {}
research_plans = {}
ethics_reviews = {}
judges = {}
judge_conflicts = {}
judging_assignments = {}
score_sheets = {}
booth_assignments = {}
awards = {}
scholarship_pools = {}


def reset_all():
    """Clear every store and reset the clock (used by tests / fresh boot)."""
    global _logical_clock, _req_counter
    with _LOCK:
        _logical_clock = _DEFAULT_CLOCK
    with _req_lock:
        _req_counter = 0
    for store in (
        fair_editions, categories, mentors, projects, research_plans,
        ethics_reviews, judges, judge_conflicts, judging_assignments,
        score_sheets, booth_assignments, awards, scholarship_pools,
    ):
        store.clear()
