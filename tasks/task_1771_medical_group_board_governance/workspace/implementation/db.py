"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts empty on every boot — no seeding.
"""
import uuid
from datetime import datetime, timezone

# --- Logical clock ---
_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


def _parse_iso(s: str) -> datetime:
    """Parse ISO8601 UTC string into an aware datetime."""
    if s is None:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt: datetime) -> str:
    """Format an aware datetime as ISO8601 UTC with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


class _Clock:
    def __init__(self):
        self._now = _parse_iso(_CLOCK_DEFAULT)

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime):
        self._now = dt

    def now_iso(self) -> str:
        return _format_iso(self._now)


clock = _Clock()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Entity timestamps: use the logical clock (system is governed by it)."""
    return clock.now_iso()


def request_timestamp() -> str:
    """Meta timestamps: wall-clock UTC with ms precision."""
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


# --- Entity stores (empty at boot) ---
policy = None  # singleton GovernancePolicy dict or None
physicians = {}
board_seats = {}
committees = {}
buy_in_offers = {}
motions = {}
votes = {}
capital_calls = {}
assessments = {}
distributions = {}
exit_valuations = {}
coi_disclosures = {}
merger_proposals = {}
