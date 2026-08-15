"""In-memory data store and logical house clock.

Storage is process-local dicts keyed by id. Nothing is seeded at startup;
every entity is created through the declared API surface. The logical clock
starts at 2026-08-01T00:00:00Z and only moves via POST /_clock/set_current_utc.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Entity tables (keyed by id)
# ---------------------------------------------------------------------------
artists = {}
booking_agents = {}
shows = {}
date_holds = {}
offers = {}
deals = {}
ticket_tiers = {}
ticket_sales = {}          # value dict carries a private "_alloc" {tier_id: qty}
advance_checklists = {}    # keyed by checklist id; also indexed by show_id
support_acts = {}
expense_receipts = {}
ancillary_revenues = {}
settlements = {}           # 1:1 with show
wire_transfers = {}
cancellation_events = {}

# Monotonic insertion counter (stable ordering / FIFO tie-breaks).
_seq = [0]

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = [DEFAULT_CLOCK]
_last_stamp = [DEFAULT_CLOCK - timedelta(milliseconds=1)]


def now():
    """Current logical time (UTC, tz-aware)."""
    return _clock[0]


def set_clock(dt):
    _clock[0] = dt


def mint_stamp():
    """A logical timestamp guaranteed strictly greater than any prior stamp.

    Keeps created_at unique and FIFO-ordered even when many records are
    minted at the same logical instant.
    """
    t = _clock[0]
    if t <= _last_stamp[0]:
        t = _last_stamp[0] + timedelta(milliseconds=1)
    _last_stamp[0] = t
    return t


def fmt_dt(dt):
    """ISO-8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def mint_id():
    return str(uuid.uuid4())


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_common(entity):
    """Populate id/created_at/updated_at/version on a fresh entity dict."""
    ts = mint_stamp()
    entity["id"] = mint_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def new_ledger(entity):
    """Ledger records (TicketSale/AncillaryRevenue/CancellationEvent): id+created_at only."""
    ts = mint_stamp()
    entity["id"] = mint_id()
    entity["created_at"] = ts
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Mutation bookkeeping: refresh updated_at, bump version."""
    entity["updated_at"] = mint_stamp()
    entity["version"] = entity.get("version", 1) + 1


def bump_show(show):
    touch(show)


# ---------------------------------------------------------------------------
# Lazy time-based transitions (PRD section 2.7)
# ---------------------------------------------------------------------------
def sweep_time_transitions():
    """Apply clock-driven transitions: DateHold expiry and ADVANCED->SHOW_NIGHT.

    Evaluated lazily: runs before every request is handled so any read or
    write observes the post-transition state.
    """
    t = now()
    for h in list(date_holds.values()):
        if h["status"] == "ACTIVE" and t >= h["hold_expires_at_utc"]:
            h["status"] = "EXPIRED"
            touch(h)
        elif h["status"] == "CHALLENGED" and h.get("challenge_window_ends_at_utc") is not None \
                and t >= h["challenge_window_ends_at_utc"]:
            h["status"] = "EXPIRED"
            touch(h)
    for s in list(shows.values()):
        if s["status"] == "ADVANCED" and s["doors_at_utc"] <= t < s["curfew_at_utc"]:
            s["status"] = "SHOW_NIGHT"
            touch(s)
