"""In-memory data store. Resets on every process boot."""

from datetime import datetime, timezone


def utcnow_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits, suffixed with 'Z'."""
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 UTC. Accept trailing Z."""
    if not isinstance(s, str):
        raise ValueError("Expected ISO 8601 string")
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as e:
        raise ValueError(f"Invalid ISO 8601: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class _Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.households = {}             # id -> dict
        self.members = {}                # id -> dict
        self.applications = {}           # id -> dict
        self.ebt_cards = {}              # id -> dict
        self.monthly_allotments = {}     # id -> dict
        self.eligible_categories = {}    # id -> dict
        self.purchase_transactions = {}  # id -> dict
        self.fraud_flags = {}            # id -> dict
        self.abawd_waivers = {}          # id -> dict
        self.emergency_proclamations = {}  # id -> dict
        # SystemClock: a single register. None means "no override — use real wall clock".
        # In practice, tests always set it before relying on it. Until tests set it,
        # current_utc returns the real wall-clock time as ISO string.
        self._clock_override = None
        # Reusable system clock object (id stable across reads, created lazily on first read).
        self._clock_id = None
        self._clock_created_at = None

    # ----- System clock -----
    def clock_set(self, iso_value: str):
        # Validate & normalize through parse_iso then reformat.
        dt = parse_iso(iso_value)
        self._clock_override = dt
        if self._clock_id is None:
            import uuid
            self._clock_id = str(uuid.uuid4())
            self._clock_created_at = iso_from_datetime(dt)
        return self.clock_get()

    def clock_get(self):
        import uuid
        if self._clock_override is not None:
            current = iso_from_datetime(self._clock_override)
        else:
            current = utcnow_iso()
        if self._clock_id is None:
            self._clock_id = str(uuid.uuid4())
            self._clock_created_at = current
        return {
            "id": self._clock_id,
            "created_at": self._clock_created_at,
            "current_utc": current,
        }

    def current_utc_dt(self) -> datetime:
        """Return the effective current UTC datetime."""
        if self._clock_override is not None:
            return self._clock_override
        return datetime.now(tz=timezone.utc)

    def current_utc_iso(self) -> str:
        return iso_from_datetime(self.current_utc_dt())


db = _Store()
