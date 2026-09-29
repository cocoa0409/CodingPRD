"""In-memory data store, the logical clock and row helpers.

Storage is process-local and starts completely EMPTY on every boot: no entity is
ever seeded, preloaded or hardcoded here.  Tests build every precondition
through the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD §2.4 — the logical clock starts at this fixed instant and never reads wall time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "restaurants",
    "tier_policies",
    "daypart_profiles",
    "staff_members",
    "deployments",
    "timer_loops",
    "merge_slots",
    "pull_forward_orders",
    "accuracy_incidents",
    "throughput_reports",
    "coaching_interventions",
    "forecast_overrides",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.car_sequences = {}      # restaurant_id -> last assigned car_sequence
        self.slot_sequences = {}     # restaurant_id -> last assigned sequence_index


db = Store()


# --------------------------------------------------------------------------- ids
def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------- time formatting
def fmt_dt(value):
    """Whole-second ISO-8601 UTC (logical-clock stamps)."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(value):
    """ISO-8601 UTC with three fractional digits (created_at / updated_at / meta)."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (value.microsecond // 1000)


def now():
    return db.clock


def minute_of_day(value):
    return value.hour * 60 + value.minute


def seconds_between(later, earlier):
    return int((later - earlier).total_seconds())


def shift(value, seconds):
    return value + timedelta(seconds=seconds)


# ------------------------------------------------------------------ row helpers
def base_row():
    return {
        "id": new_id(),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }


def touch(row):
    row["updated_at"] = db.clock
    row["version"] = row["version"] + 1


def snapshot(row):
    return dict((k, v) for k, v in row.items() if k not in ("updated_at", "version"))


def touch_if_changed(row, snap):
    """Bump version/updated_at only when the row actually changed."""
    if snapshot(row) != snap:
        touch(row)
        return True
    return False


# --------------------------------------------------------------------- rounding
def rhu(value, places=0):
    """Round half up on decimal arithmetic (PRD §2.9)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ------------------------------------------------------------------- selections
def by_restaurant(collection, restaurant_id):
    return [row for row in collection.values() if row.get("restaurant_id") == restaurant_id]


def sorted_rows(rows):
    """Default list ordering: created_at ascending, insertion order for ties."""
    return sorted(rows, key=lambda r: r["created_at"])
