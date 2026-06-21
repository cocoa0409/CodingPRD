"""Server-driven logical UTC clock.

PRD §3.14: a LeagueAdmin may drive the server's current UTC instant via
POST /_clock/set_current_utc; that logical clock is what the system reads
for every comparison against "the current clock" (settlement gate, no-show
gate, decline-penalty lead-time computation).

The clock starts at real wall-clock UTC on each fresh boot and can be
overridden by the test-driving endpoint. All other timestamps
(created_at / updated_at / api_request_timestamp) use real wall-clock UTC
per PRD §2.4 / §2.2.
"""
from datetime import datetime, timezone

_override = None  # datetime (aware UTC) or None


def set_current_utc(dt):
    global _override
    _override = dt


def now():
    """Logical 'current clock' used for time-gated transitions / penalties."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def reset():
    global _override
    _override = None
