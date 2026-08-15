"""In-memory data store, logical clock, id/timestamp/number helpers.

No disk persistence. The store starts empty on every boot; nothing is seeded.
The logical clock defaults to exactly 2026-08-01T00:00:00Z and is only moved by
POST /_clock/set_current_utc. All entity timestamps (created_at, updated_at and
business timestamps) are stamped from the logical clock; temporal rules never
consult wall time.
"""
import itertools
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# The plant logical clock (module-level; rebound only by routes/clock.py).
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.contracts = {}            # IngredientContract
        self.index_readings = {}       # PriceIndexReading (append-only log)
        self.semolina_lots = {}        # SemolinaLot
        self.recipes = {}              # Recipe
        self.recipe_ingredients = {}   # RecipeIngredient (junction, immutable)
        self.production_lines = {}     # ProductionLine
        self.extrusion_dies = {}       # ExtrusionDie
        self.production_runs = {}      # ProductionRun
        self.drying_sessions = {}      # DryingSession
        self.packaging_jobs = {}       # PackagingJob
        self.finished_goods_lots = {}  # FinishedGoodsLot
        self.warehouse_zones = {}      # WarehouseZone
        self.pest_inspections = {}     # PestInspection
        self.gluten_tests = {}         # GlutenTest


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------- clock ------
def clock_now():
    return LOGICAL_CLOCK


def clock_today():
    return LOGICAL_CLOCK.date()


def set_clock(dt):
    global LOGICAL_CLOCK
    LOGICAL_CLOCK = dt


def fmt_dt(dt):
    """ISO 8601 UTC; three fractional digits when sub-second, else plain seconds."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt_ms(dt):
    """ISO 8601 UTC always with three fractional digits (meta timestamps)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_datetime(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date string, else None."""
    if not isinstance(value, str):
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------- numbers ----
def dec(value):
    """Decimal from a JSON number without float artifacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def num_out(value):
    """Normalize a Decimal for JSON: int when integral, else float."""
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------- entities ---
def touch(entity):
    """Refresh updated_at and bump version on a mutable (common_fields) entity."""
    entity["updated_at"] = clock_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created versioned entity."""
    entity["created_at"] = clock_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def new_log_entry(entity):
    """Stamp id/created_at only (append-only logs: readings, ingredient rows)."""
    entity["created_at"] = clock_now()
    entity["_seq"] = next_seq()
    return entity
