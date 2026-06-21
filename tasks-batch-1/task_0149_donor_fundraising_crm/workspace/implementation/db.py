"""In-memory data store for the Donor & Fundraising CRM API.

Storage is process-local Python dicts keyed by id. No persistence, no seeding.
A fresh process (per-test-server restart) starts completely empty.

Also hosts the logical UTC clock (§2.9) and monotonic ordering helpers.
"""

import threading
import uuid
from datetime import datetime, timezone

# Global lock so each request's cascade is atomic against concurrent requests.
LOCK = threading.RLock()

# One dict per entity collection, keyed by id.
households = {}
donors = {}
employers = {}
campaigns = {}
appeals = {}
pledges = {}
pledge_installments = {}
gifts = {}
soft_credits = {}
match_claims = {}
planned_gifts = {}
acknowledgements = {}
segments = {}

# Monotonic counter giving every created row a strict total order, used as the
# tie-breaker for created_at sorting (created_at can collide at ms precision,
# and the logical clock can be frozen so many rows share a created_at).
_seq_counter = 0

# The logical UTC clock. Defaults to None -> fall back to wall-clock time until
# an admin sets it via POST /_clock/set_current_utc.
_logical_clock = None


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def now_iso():
    """Wall-clock ISO 8601 UTC with three fractional digits, used only for the
    response-envelope meta timestamp (api_request_timestamp), which records the
    real instant the server answered the request."""
    dt = datetime.now(timezone.utc)
    return _format_iso(dt)


def clock_iso():
    """Logical-clock ISO 8601 UTC with three fractional digits, used for all
    resource timestamps (created_at / updated_at / acknowledged_at). These
    anchor the system's time-gated computations: a gift's created_at becomes a
    donor's last_gift_at (lapse window, §2.9/§3.7), and a pledge's created_at
    anchors its installment due_on offsets (overdue detection, §3.5). Per §2.9
    the logical clock governs these flows so they are testable deterministically."""
    return _format_iso(logical_now())


def _format_iso(dt):
    # Millisecond precision, trailing Z.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_logical_clock(dt):
    global _logical_clock
    _logical_clock = dt


def logical_now():
    """The current logical clock instant as a timezone-aware datetime.

    Used for all *time-gated business comparisons* (installment due dates,
    lapse windows). Falls back to wall-clock when never set."""
    if _logical_clock is not None:
        return _logical_clock
    return datetime.now(timezone.utc)
