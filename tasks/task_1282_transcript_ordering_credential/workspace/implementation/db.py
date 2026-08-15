"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "students": {},
    "student_records": {},
    "recipients": {},
    "holds": {},
    "identity_verifications": {},
    "orders": {},
    "order_line_items": {},
    "archived_retrievals": {},
    "consent_grants": {},
    "verification_requests": {},
    "fee_schedules": {},
    "payments": {},
    "reissue_requests": {},
    "clearinghouse_batches": {},
    "audit_events": {},
}

# Logical clock state. Startup default is exactly 2026-08-01T00:00:00Z (PRD 2.4).
CLOCK = {"current_utc": "2026-08-01T00:00:00Z"}


def new_id():
    return str(uuid.uuid4())


def logical_now_iso():
    """Current logical clock reading, normalized to ISO 8601 UTC, 3 fractional digits."""
    return to_iso_ms(parse_iso(CLOCK["current_utc"]))


def wall_now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits (for meta)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_iso_ms(dt):
    """Serialize an aware datetime to ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
