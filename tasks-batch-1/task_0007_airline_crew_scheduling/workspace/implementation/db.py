"""In-memory data store. Populated only via declared endpoints — never seeded."""
import uuid
from datetime import datetime, timezone


# Logical clock (PRD §2.6). Defaults to real wall-clock at boot; tests overwrite
# via POST /_clock/set_current_utc before any meaningful operation.
current_utc: datetime = datetime.now(timezone.utc)


# Primary stores. Keys are entity ids (UUIDs).
crew_members: dict = {}
pairings: dict = {}
flight_legs: dict = {}
bids: dict = {}
assignments: dict = {}
sick_calls: dict = {}
reserve_callups: dict = {}
trip_trades: dict = {}


def new_id() -> str:
    """Server-minted UUID without any type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def iso_ms(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso_ms(current_utc)


def set_clock(new_utc: datetime) -> None:
    """Bare clock setter — cascades handled at the route layer."""
    global current_utc
    current_utc = new_utc
