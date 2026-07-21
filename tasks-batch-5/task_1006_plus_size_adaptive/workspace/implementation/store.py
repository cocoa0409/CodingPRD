"""In-memory data store, logical clock, and shared helpers.

Every process boot starts with an entirely empty store. Nothing is seeded,
preloaded, or hardcoded here — all entities are created via the API surface.
"""
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
# Loyalty / money
REDEEM_VALUE_CENTS_PER_POINT = 5
REDEEM_CAP_PCT = "0.30"
TIER_DISCOUNT = {"STANDARD": "0.00", "INSIDER": "0.05", "VIP": "0.10"}
EARN_CENTS_PER_POINT = 100
TIER_INSIDER_MIN = 500
TIER_VIP_MIN = 2000
TIER_UP_BONUS_CENTS = {"INSIDER": 1000, "VIP": 2500}
TIER_RANK = {"STANDARD": 0, "INSIDER": 1, "VIP": 2}

STYLING_FEE_CENTS = {"ESSENTIALS": 0, "SIGNATURE": 2500, "LUXE": 5000}

# Temporal / threshold policy constants (pinned from task design docs; the
# scaffold names them symbolically without inline numeric values).
RETURN_WINDOW_DAYS = 30
TRYON_WINDOW_DAYS = 7
LATE_CANCEL_WINDOW_HOURS = 24
LATE_CANCEL_FEE_CENTS = 1500
NO_SHOW_SUSPEND_THRESHOLD = 3

# Enum vocabularies
ADAPTIVE_FEATURES = {"MAGNETIC_CLOSURE", "SEATED_CUT", "SENSORY_FRIENDLY",
                     "ONE_HANDED", "PORT_ACCESS"}
PRODUCT_CATEGORIES = {"TOPS", "BOTTOMS", "DRESSES", "OUTERWEAR", "INTIMATES"}
SPECIALTIES = {"ADAPTIVE", "PLUS_FORMAL", "MATERNITY"}
APPOINTMENT_TOPICS = {"GENERAL", "ADAPTIVE", "PLUS_FORMAL", "MATERNITY"}
RETURN_TYPES = {"RETURN", "EXCHANGE"}
FIT_VERDICTS = {"RUNS_SMALL", "TRUE_TO_SIZE", "RUNS_LARGE"}
REFUND_DESTINATIONS = {"WALLET", "ORIGINAL"}
PLAN_TIERS = {"ESSENTIALS", "SIGNATURE", "LUXE"}
CADENCES = {"MONTHLY", "QUARTERLY"}
ROLES = {"Anonymous", "Customer", "FitSpecialist", "StoreManager"}

CLOCK_DEFAULT = "2026-07-01T00:00:00Z"


def parse_dt(s):
    """Parse an ISO-8601 string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_wall():
    return datetime.now(timezone.utc)


class Store:
    def __init__(self):
        self.customers = {}
        self.specialists = {}
        self.products = {}
        self.variants = {}
        self.appointments = {}
        self.orders = {}
        self.order_lines = {}
        self.returns = {}
        self.subscriptions = {}
        self.shipments = {}
        self._seq = 0
        self._clock = parse_dt(CLOCK_DEFAULT)

    # ---- id / sequence ----
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- logical clock ----
    def clock_now(self):
        return self._clock

    def set_clock(self, iso_str):
        self._clock = parse_dt(iso_str)
        return self._clock


db = Store()


def new_record(full=True):
    """Create a record dict with common server-managed fields.

    full=True  -> id, created_at, updated_at, version, _seq
    full=False -> id, created_at, _seq (OrderLine: immutable snapshot)
    """
    ts = iso(now_wall())
    rec = {"id": db.new_id(), "created_at": ts, "_seq": db.next_seq()}
    if full:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version for a mutated full record."""
    rec["updated_at"] = iso(now_wall())
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal keys for output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
