"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "projects": {},
    "trade_packages": {},
    "bids": {},
    "scope_gaps": {},
    "subcontracts": {},
    "negotiation_rounds": {},
    "insurance_certificates": {},
    "bond_decisions": {},
    "schedule_of_values": {},
    "change_orders": {},
}

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
