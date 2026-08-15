"""In-memory data store for the fraud ops API.

All state is process-local. The store starts empty on every boot — no seeding.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(iso: str) -> datetime:
    """Parse an ISO-8601 timestamp accepting trailing 'Z'."""
    s = iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_iso() -> str:
    return _clock.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_clock.microsecond // 1000:03d}Z"


_clock: datetime = _parse_iso(_DEFAULT_CLOCK_ISO)


def get_clock() -> datetime:
    return _clock


def get_clock_iso() -> str:
    return _now_iso()


def set_clock(iso: str) -> datetime:
    global _clock
    _clock = _parse_iso(iso)
    return _clock


# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id)
# ---------------------------------------------------------------------------

accounts: dict = {}
cards: dict = {}
rule_sets: dict = {}
auth_transactions: dict = {}
fraud_alerts: dict = {}
verification_contacts: dict = {}
compromised_card_events: dict = {}
reissue_decisions: dict = {}
travel_notices: dict = {}
chargeback_cases: dict = {}
loss_entries: dict = {}
recovery_filings: dict = {}
fraud_rings: dict = {}
ring_memberships: dict = {}

# Ring confirmation remembers which card ids the ring raised to WATCH so that a
# later dismiss can compensate exactly those cards.
ring_raised_watch: dict = {}  # ring_id -> list[card_id]
