"""In-memory data store. Starts empty on every process boot — no seeding."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# A single lock makes every request handler atomic, which keeps multi-resource
# cascades and OCC checks consistent.
LOCK = threading.RLock()

# Insertion counter — used as a stable secondary sort key so ordering never
# depends on uuid string ordering.
_seq = itertools.count(1)

# One dict per entity type, keyed by id.
courts = {}
cases = {}
parties = {}
filings = {}
service_of_process = {}
deadlines = {}
motions = {}
orders = {}
fee_waivers = {}
hearings = {}
judgments = {}
appeals = {}

# Logical system clock (PRD 2.6). Defaults to wall-clock at boot; a SystemAdmin
# may override it via POST /_clock/set_current_utc.
_clock = {"current": datetime.now(timezone.utc)}


def now_clock():
    return _clock["current"]


def set_clock(dt):
    _clock["current"] = dt


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Wall-clock timestamp for created_at/updated_at (3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_record():
    ts = iso_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version."""
    record["updated_at"] = iso_now()
    record["version"] = record.get("version", 1) + 1
