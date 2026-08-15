"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "customers": {},
    "artworks": {},
    "substrates": {},
    "ink_recipes": {},
    "dies": {},
    "presses": {},
    "jobs": {},
    "measurements": {},
    "rolls": {},
    "letters": {},
}


def new_id():
    """Server-minted UUID with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
