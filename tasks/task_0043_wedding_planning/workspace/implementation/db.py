"""In-memory data store and helpers."""
import datetime
import threading
import uuid


_LOCK = threading.RLock()


# Simulated logical clock — only advanced via /_clock/advance.
# Default to current real time so that tests not exercising clock get sensible behavior.
_CLOCK_SECONDS = [int(datetime.datetime.now(datetime.timezone.utc).timestamp())]


def lock():
    return _LOCK


def now_clock() -> int:
    """Returns the current logical clock as Unix seconds."""
    return _CLOCK_SECONDS[0]


def set_clock(ts: int) -> None:
    _CLOCK_SECONDS[0] = int(ts)


def now_iso() -> str:
    """Real wall clock ISO 8601 UTC with 3 fractional digits."""
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def gen_id() -> str:
    return str(uuid.uuid4())


# --- in-memory tables, keyed by id ---
projects = {}             # id -> WeddingProject dict
templates = {}            # id -> ProjectTemplate dict
milestones = {}           # id -> Milestone dict
vendors = {}              # id -> Vendor dict
quotes = {}               # id -> Quote dict
contracts = {}            # id -> Contract dict
change_orders = {}        # id -> ChangeOrder dict
settlements = {}          # id -> Settlement dict
timeline_slots = {}       # id -> TimelineSlot dict
guests = {}               # id -> Guest dict
audit_entries = {}        # id -> AuditEntry dict
performance_ratings = {}  # id -> PerformanceRating dict

# Cross-cutting registries
esign_completed_envelope_ids = set()  # Envelope ids that have received ESIGN_COMPLETED


def add_common_create(obj: dict, with_version: bool = True) -> dict:
    """Adds id, created_at, updated_at, version to a fresh dict."""
    obj["id"] = gen_id()
    obj["created_at"] = now_iso()
    if with_version:
        obj["updated_at"] = obj["created_at"]
        obj["version"] = 1
    return obj


def bump(obj: dict) -> None:
    """Update updated_at and version after a server-side mutation."""
    if "version" in obj:
        obj["version"] = int(obj["version"]) + 1
    if "updated_at" in obj:
        obj["updated_at"] = now_iso()


def reset_all():
    """Used for test reset / debug only."""
    with _LOCK:
        for d in (projects, templates, milestones, vendors, quotes, contracts,
                  change_orders, settlements, timeline_slots, guests,
                  audit_entries, performance_ratings):
            d.clear()
        esign_completed_envelope_ids.clear()
        _CLOCK_SECONDS[0] = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
