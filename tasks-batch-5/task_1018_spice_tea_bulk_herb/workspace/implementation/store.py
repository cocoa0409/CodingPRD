"""In-memory data store and shared helpers.

State lives in module-level dicts keyed by id. The process starts empty on
every boot (start.sh re-invocation wipes all state); nothing is seeded here.
"""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Entity tables (empty at startup — never seeded)
# ---------------------------------------------------------------------------
products = {}
blend_components = {}
inventory_lots = {}
production_lines = {}
batches = {}
labeling_stations = {}
tin_runs = {}
wholesale_accounts = {}
customer_orders = {}
order_lines = {}

# Monotonic insertion sequence (final deterministic tie-break / list ordering)
_seq_counter = {"n": 0}

# Logical clock (UTC). Startup default per PRD 2.7; never falls back to wall time.
DEFAULT_CLOCK_ISO = "2026-07-01T00:00:00Z"
clock = {"now": None}  # datetime, set in reset()


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def gen_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return clock["now"]


def rhu_cents(grams, unit_price):
    """round_half_up(grams * unit_price) -> integer cents."""
    val = Decimal(str(grams)) * Decimal(str(unit_price))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_rate(amount_cents, rate):
    """round_half_up(amount_cents * rate) -> integer cents."""
    val = Decimal(str(amount_cents)) * Decimal(str(rate))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(rec):
    """Refresh updated_at and bump version on any modification."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def new_common():
    """Common system fields: id, created_at, updated_at, version."""
    ts = now_iso()
    return {
        "id": gen_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def reset():
    for tbl in (products, blend_components, inventory_lots, production_lines,
                batches, labeling_stations, tin_runs, wholesale_accounts,
                customer_orders, order_lines):
        tbl.clear()
    _seq_counter["n"] = 0
    clock["now"] = parse_dt(DEFAULT_CLOCK_ISO)


# Initialise the logical clock on import.
reset()
