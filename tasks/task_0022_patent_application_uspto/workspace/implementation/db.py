"""In-memory data store and time helpers. Resets on every process boot."""

import uuid
from datetime import datetime, timezone


# ----- Time helpers ---------------------------------------------------------

def utcnow_dt() -> datetime:
    """Real wall clock — DO NOT use for business date stamping. Used only
    for response envelope api_request_timestamp where PRD does not pin the
    value to the logical clock. Business operations must call
    `db.current_utc_dt()` (the single logical clock per PRD §2.6 / §3.11)."""
    return datetime.now(tz=timezone.utc)


def iso_from_datetime(dt: datetime) -> str:
    """ISO 8601 UTC string with three fractional digits (e.g. 2025-05-24T10:30:00.123Z)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utcnow_iso() -> str:
    return iso_from_datetime(utcnow_dt())


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime. Accept trailing 'Z'."""
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
        # Entity tables
        self.applicants = {}                  # id -> dict
        self.applications = {}                # id -> dict
        self.office_actions = {}              # id -> dict
        self.office_action_responses = {}     # id -> dict
        self.maintenance_fees = {}            # id -> dict
        self.fee_payments = {}                # id -> dict
        self.pct_phase_entries = {}           # id -> dict

        # Logical clock override (None => real wall clock)
        self._clock_override = None

        # Patent number sequence (US{seq})
        self._patent_seq = 0

    # ---- Clock ----
    def set_clock(self, iso_value: str):
        self._clock_override = parse_iso(iso_value)

    def current_utc_dt(self) -> datetime:
        if self._clock_override is not None:
            return self._clock_override
        return utcnow_dt()

    def current_utc_iso(self) -> str:
        return iso_from_datetime(self.current_utc_dt())

    # ---- Patent number minting ----
    def mint_patent_number(self) -> str:
        self._patent_seq += 1
        return f"US{self._patent_seq}"


db = _Store()
