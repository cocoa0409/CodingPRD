"""In-memory data store and time helpers. Resets on every process boot.

Storage is pure in-memory (Python dicts keyed by id). Nothing is persisted to
disk and NO entity is seeded at startup — every row is created by a test via the
declared API surface.
"""

import uuid
from datetime import datetime, timezone


# ----- Time helpers ---------------------------------------------------------

def utcnow_dt() -> datetime:
    """Real wall clock. Used only for the response envelope's
    api_request_timestamp, which the PRD does not pin to the logical clock.
    Business date stamping must use db.current_utc_dt() (the logical clock
    driven by POST /_clock/set_current_utc — PRD §2.7)."""
    return datetime.now(tz=timezone.utc)


def iso_from_datetime(dt: datetime) -> str:
    """ISO 8601 UTC string with three fractional digits
    (e.g. 2025-05-24T10:30:00.123Z)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utcnow_iso() -> str:
    return iso_from_datetime(utcnow_dt())


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime. Accepts trailing 'Z'."""
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


def new_id() -> str:
    return str(uuid.uuid4())


# ----- In-memory store ------------------------------------------------------

class _Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # Entity tables (id -> dict)
        self.applicants = {}
        self.attorneys = {}
        self.applications = {}
        self.nice_classes = {}
        self.goods_services = {}
        self.office_actions = {}
        self.office_action_responses = {}
        self.statements_of_use = {}
        self.ttab_proceedings = {}
        self.registrations = {}
        self.maintenance_filings = {}
        self.madrid_applications = {}
        self.docket_deadlines = {}

        # Logical clock override (None => real wall clock)
        self._clock_override = None

        # Registration serial sequence (unique across Registration)
        self._registration_seq = 0

    # ---- Clock ----
    def set_clock(self, iso_value: str):
        self._clock_override = parse_iso(iso_value)

    def current_utc_dt(self) -> datetime:
        if self._clock_override is not None:
            return self._clock_override
        return utcnow_dt()

    def current_utc_iso(self) -> str:
        return iso_from_datetime(self.current_utc_dt())

    # ---- Registration number minting ----
    def mint_registration_number(self) -> str:
        self._registration_seq += 1
        return str(7000000 + self._registration_seq)


db = _Store()
