"""In-memory data store.

Single global namespace; rebuilt each process boot. The test harness
restarts the server before every test, so we never persist across runs.
"""
import uuid
from datetime import datetime, timezone


# All entity stores keyed by id
employees = {}             # id -> Employee dict
w4_forms = {}              # id -> W4Form dict
paycheck_runs = {}         # id -> PaycheckRun dict
paychecks = {}             # id -> Paycheck dict
garnishment_orders = {}    # id -> GarnishmentOrder dict
garnishment_deductions = {}  # id -> GarnishmentDeduction dict
remittances = {}           # id -> Remittance dict
tax_rate_tables = {}       # id -> TaxRateTable dict

# Server clock override (set via POST /_clock/set_current_utc).
# When None, real wall-clock is used.
_clock_override = None


def new_id():
    return str(uuid.uuid4())


def now_utc():
    """Returns the current UTC datetime, honoring any test clock override."""
    global _clock_override
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def set_clock(iso_str):
    """Set the server's NOW_UTC clock for test-driving."""
    global _clock_override
    if iso_str is None:
        _clock_override = None
        return
    # Accept Z-suffixed ISO 8601 by mapping Z to +00:00
    s = iso_str
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock_override = dt.astimezone(timezone.utc)


def iso8601(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Truncate (not round) microseconds to 3 fractional digits
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(ms)


def stamp_common(entity, *, include_version=True):
    """Initialize created_at/updated_at/version on a freshly built entity."""
    now = now_utc()
    entity["created_at"] = now
    if include_version:
        entity["updated_at"] = now
        entity["version"] = 0
    return entity


def bump(entity):
    """Refresh updated_at and increment version on a mutated entity."""
    entity["updated_at"] = now_utc()
    entity["version"] = entity.get("version", 0) + 1
