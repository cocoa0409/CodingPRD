"""In-memory data store. Populated only via the declared API surface."""
import uuid
from datetime import datetime, timezone

# --- Entities keyed by id ---
corporate_accounts = {}
gift_basket_templates = {}
component_skus = {}
branding_profiles = {}
corporate_orders = {}
recipients = {}
message_proofs = {}
inventory_reservations = {}
assembly_stations = {}
assembly_tasks = {}
shipping_zones = {}
shipments = {}
budget_approvals = {}
recurring_series = {}

# Order-scoped monotonic counter (currently unused external, kept for future).
_seq = 0

# Logical clock — server starts at fixed default 2026-03-01T00:00:00Z per PRD §3.1
_clock_now = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
# Track last observed calendar month for ytd_spend_cents auto-reset (PRD §3.2)
_last_seen_month = (_clock_now.year, _clock_now.month)


def clock_now():
    return _clock_now


def clock_set(dt: datetime):
    global _clock_now
    _clock_now = dt


def get_last_seen_month():
    return _last_seen_month


def set_last_seen_month(ym):
    global _last_seen_month
    _last_seen_month = ym


def reset_all():
    """Fresh-boot reset — not required in single-process boot but keeps tests safe."""
    global _clock_now, _last_seen_month, _seq
    corporate_accounts.clear()
    gift_basket_templates.clear()
    component_skus.clear()
    branding_profiles.clear()
    corporate_orders.clear()
    recipients.clear()
    message_proofs.clear()
    inventory_reservations.clear()
    assembly_stations.clear()
    assembly_tasks.clear()
    shipping_zones.clear()
    shipments.clear()
    budget_approvals.clear()
    recurring_series.clear()
    _clock_now = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    _last_seen_month = (_clock_now.year, _clock_now.month)
    _seq = 0


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Current clock, formatted as ISO 8601 UTC with 3 fractional digits."""
    return format_iso(_clock_now)


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC string; accepts trailing 'Z' or offset."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch_common_fields(entity: dict, is_create: bool = False):
    """Set/refresh created_at/updated_at/version."""
    ts = now_iso()
    if is_create:
        entity["created_at"] = ts
        entity["updated_at"] = ts
        entity["version"] = 1
    else:
        entity["updated_at"] = ts
        entity["version"] = entity.get("version", 1) + 1


def maybe_reset_ytd_on_mutation():
    """Zero ytd_spend_cents when clock crosses into a new UTC calendar month (PRD §3.2)."""
    global _last_seen_month
    cur = (_clock_now.year, _clock_now.month)
    if cur != _last_seen_month:
        for acc in corporate_accounts.values():
            acc["ytd_spend_cents"] = 0
        _last_seen_month = cur
