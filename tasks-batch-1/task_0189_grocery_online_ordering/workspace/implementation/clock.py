"""Server-driven logical UTC clock.

PRD §3.9: a PlatformAdmin may drive the server's current UTC instant via
POST /_clock/set_current_utc; that clock is what the system reads when
stamping staged_at and when evaluating the cold-chain expiry.

The clock starts at real wall-clock UTC on each fresh boot and can be
overridden by the test-driving endpoint. All timestamps elsewhere
(created_at / updated_at / api_request_timestamp) use real wall-clock UTC
per PRD §2.4 / §2.2 unless they are the logical fields above.
"""
from datetime import datetime, timezone

_override = None  # datetime (aware UTC) or None


def set_current_utc(dt):
    global _override
    _override = dt


def now():
    """Logical 'current clock' used for staged_at + cold-chain evaluation."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def reset():
    global _override
    _override = None
