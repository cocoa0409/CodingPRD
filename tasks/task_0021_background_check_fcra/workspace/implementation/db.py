"""In-memory data store. Resets on every process boot.

No entity seeding occurs anywhere — the SystemClock is materialised lazily on
first read or first write, but no domain entity (Applicant, Application,
Jurisdiction, ConsentDisclosure, BackgroundCheckOrder, Verification,
AdverseAction, AuditLog) is pre-populated. Tests build all preconditions via the
declared API surface.
"""

from datetime import datetime, timezone


def utcnow_iso() -> str:
    """Real-wall-clock ISO 8601 UTC with three fractional digits + 'Z'."""
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s) -> datetime:
    """Parse an ISO 8601 timestamp (accept trailing Z)."""
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
        # All business entities — start empty on every boot.
        self.jurisdictions = {}            # id -> dict
        self.applicants = {}               # id -> dict
        self.applications = {}             # id -> dict
        self.consents = {}                 # id -> dict
        self.orders = {}                   # id -> dict (BackgroundCheckOrder)
        self.verifications = {}            # id -> dict
        self.adverse_actions = {}          # id -> dict
        self.audit_logs = []               # ordered list, appended

        # Indexes for cheap lookups.
        # Recorded actors keyed by application_id for segregation-of-duties:
        #   - conditional_offer_actor[application_id] = X-User-ID
        self.conditional_offer_actor = {}

        # SystemClock singleton — materialised lazily on first read/write.
        self._clock_override = None
        self._clock_id = None
        self._clock_created_at = None

    # ----- SystemClock -----
    def clock_set(self, iso_value: str):
        dt = parse_iso(iso_value)
        self._clock_override = dt
        if self._clock_id is None:
            self._clock_id = "singleton"
            self._clock_created_at = iso_from_datetime(dt)
        return self.clock_get()

    def clock_get(self):
        if self._clock_override is not None:
            current = iso_from_datetime(self._clock_override)
        else:
            current = utcnow_iso()
        if self._clock_id is None:
            self._clock_id = "singleton"
            self._clock_created_at = current
        return {
            "id": self._clock_id,
            "created_at": self._clock_created_at,
            "current_utc": current,
        }

    def current_utc_dt(self) -> datetime:
        if self._clock_override is not None:
            return self._clock_override
        return datetime.now(tz=timezone.utc)

    def current_utc_iso(self) -> str:
        return iso_from_datetime(self.current_utc_dt())


db = _Store()
