"""In-memory data store (PRD §2.4, §2.5).

ALL state lives in module-level dicts keyed by id. Nothing is persisted to
disk and nothing is seeded at startup — the store is empty on every boot and
every entity is created by tests through the declared API surface. start.sh is
re-invoked before every per-test server, so a fresh process wipes all state.

A logical clock (`_now`) holds the server's notion of "now"; it is advanced by
POST /_clock/set_current_utc and read by all due-date / hold / posture logic.
It defaults to real wall-clock UTC until the test sets it.
"""
import threading
import uuid
from datetime import datetime, timezone

# ── Entity tables ────────────────────────────────────────────────────────────
merchants = {}
borrowers = {}
applications = {}
disclosure_acceptances = {}
loans = {}
installments = {}
payments = {}
returns = {}
autopay_mandates = {}
merchant_settlements = {}

# Insertion-order counter — used as a stable tie-break / created_at-ordering key
# independent of timestamp granularity (multiple rows can share a millisecond).
_seq_lock = threading.Lock()
_seq = 0

# Logical clock: server "now". None => use real wall clock.
_now = None


def reset():
    """Clear every table (used only for in-process test isolation, never at boot
    with seeded data)."""
    for table in (
        merchants, borrowers, applications, disclosure_acceptances, loans,
        installments, payments, returns, autopay_mandates, merchant_settlements,
    ):
        table.clear()
    global _now, _seq
    _now = None
    _seq = 0


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def now():
    """Current server instant as a timezone-aware UTC datetime."""
    if _now is not None:
        return _now
    return datetime.now(timezone.utc)


def set_now(dt):
    global _now
    _now = dt


def iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits + 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
