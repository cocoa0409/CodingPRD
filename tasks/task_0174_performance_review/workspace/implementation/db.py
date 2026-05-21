"""In-memory data store and ID/timestamp utilities."""

import secrets
import string
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def new_id() -> str:
    """Server-minted UUID with no type prefix (per PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Random request id starting with 'req_' (per PRD §2.2)."""
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def utcnow_iso() -> str:
    """Wall-clock UTC timestamp with millisecond precision (3 fractional digits)."""
    now = datetime.now(timezone.utc)
    return _format_iso(now)


def _format_iso(dt: datetime) -> str:
    """Format a datetime to ISO 8601 UTC with three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # millisecond precision
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = int(dt.microsecond / 1000)
    return f"{s}.{millis:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    """In-memory data store. Single global lock guards every mutation
    so that all cascades and budget races serialise cleanly."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.employees: Dict[str, Dict[str, Any]] = {}
        self.cycles: Dict[str, Dict[str, Any]] = {}
        self.review_cases: Dict[str, Dict[str, Any]] = {}
        self.goals: Dict[str, Dict[str, Any]] = {}
        self.feedback_requests: Dict[str, Dict[str, Any]] = {}
        self.calibration_sessions: Dict[str, Dict[str, Any]] = {}
        self.pip_cases: Dict[str, Dict[str, Any]] = {}
        self.comp_plans: Dict[str, Dict[str, Any]] = {}
        self.audit_events: list = []


# Single global store instance, imported by routes/services.
store = Store()
