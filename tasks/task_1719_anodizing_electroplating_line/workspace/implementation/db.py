"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding.
"""
import secrets
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.customers = {}
        self.fixtures = {}
        self.compat_rules = {}
        self.baths = {}
        self.titrations = {}        # id -> BathTitration
        self.doses = {}             # id -> DoseEvent
        self.work_orders = {}
        self.load_runs = {}
        self.inspections = {}
        self.salt_spray_lots = {}
        self.permits = {}
        self.samples = {}
        self.manifests = {}
        self.manifest_line_items = {}


store = Store()


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _DEFAULT_CLOCK


def get_clock() -> datetime:
    return _clock


def set_clock(dt: datetime) -> None:
    global _clock
    _clock = dt


def now_iso() -> str:
    """Current logical clock as ISO 8601 UTC with three fractional digits."""
    return format_ts(_clock)


def format_ts(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits.

    Produces e.g. '2026-08-01T00:00:00.000Z'.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + secrets.token_hex(12)
