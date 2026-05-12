"""In-memory data store and shared helpers."""
import threading
import uuid
from decimal import Decimal, ROUND_HALF_UP

from clock import current_clock, iso


# Tables (id -> row dict). Insertion order preserved by dict for stable list/sort.
volunteers: dict = {}
skills: dict = {}
volunteer_skills: dict = {}
activities: dict = {}
activity_roles: dict = {}
applications: dict = {}
hour_adjustments: dict = {}
point_mall_items: dict = {}
redemption_orders: dict = {}
certificate_templates: dict = {}
certificates: dict = {}
audit_logs: dict = {}
partner_sync_events: dict = {}

# Per-application leave history flag (whether ON_LEAVE was reached at any point).
# We keep this on Application as `_leave_was_reached`.

# Application points ledger: per-application unspent_points, used by FIFO redemption + expiry.
# Key: application_id -> int unspent points remaining.
application_points_ledger: dict = {}

# Tracks per-application portion already expired (for clamp on later HourAdjustment recompute).
application_points_expired: dict = {}

# Single global lock — these benchmarks test correctness, not throughput.
_lock = threading.RLock()


def lock():
    return _lock


def new_id() -> str:
    return str(uuid.uuid4())


def now_str() -> str:
    return iso(current_clock())


def init_common(row: dict, with_version: bool = True) -> dict:
    """Stamp id/created_at/updated_at/version on a freshly created row."""
    row.setdefault("id", new_id())
    ts = now_str()
    row["created_at"] = ts
    if with_version:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row: dict) -> None:
    """Bump version and refresh updated_at on mutation."""
    row["updated_at"] = now_str()
    row["version"] = int(row.get("version", 1)) + 1


def round2(value) -> float:
    """Round half-up to 2 decimals; return as float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def floor_int(value) -> int:
    from decimal import ROUND_FLOOR
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    return int(d)
